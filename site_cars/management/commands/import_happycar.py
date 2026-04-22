"""Import HappyCar insurance-auction listings into a tenant's SiteCar table.

Usage:
    python manage.py import_happycar --schema <tenant_schema>
    python manage.py import_happycar --schema s-korea --cookie 'PHPSESSID=...'
    python manage.py import_happycar --schema s-korea --pages 3 --dry-run
    python manage.py import_happycar --schema s-korea --with-gallery
    python manage.py import_happycar --schema s-korea --delete-missing

Keys on `SiteCar.external_id = "hc_<idx>"`, so reruns upsert.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import schema_context

from site_cars.models import SiteCar, SiteCarImage
from site_cars.happycar import scraper as _scraper
from site_cars.happycar import classifier as _classify
from site_cars.happycar import locations as _locations
from tenants.models import Tenant


STATUS_MAP = {
    "폐차": "pending",     # scrap → pending
    "부품": "pending",     # parts → pending
    "구제": "available",   # salvage → available
}

_MISC_TR = [
    ("낙찰자부담금", "Winner's fee"),
    ("없음", "None"),
    ("원", " won"),
]


def _tr_misc(s: str | None) -> str:
    if not s:
        return s or ""
    out = s
    for ko, en in _MISC_TR:
        out = out.replace(ko, en)
    return out


def _claims_count(row: dict) -> int:
    """Sum the leading integer from own_damage + opposing_damage.

    Source values look like '1 (873,290원)' or '- (-원)'. Mirrors the badge
    logic in happycar-app/app.py:_claims_count so the UI can render the
    same 'حادث واحد' / '{n} حوادث' chip without re-parsing text.
    """
    ih = row.get("insurance_history") or {}
    n = 0
    for key in ("own_damage", "opposing_damage"):
        m = re.match(r"\s*(\d+)", str(ih.get(key, "") or ""))
        if m:
            n += int(m.group(1))
    return n


def _parse_auction_end(s: str | None):
    """Parse '2026.04.23 08:30' → timezone-aware datetime (project TZ)."""
    if not s:
        return None
    try:
        dt = datetime.strptime(s.strip(), "%Y.%m.%d %H:%M")
    except ValueError:
        return None
    return timezone.make_aware(dt) if settings.USE_TZ else dt


def _description(row: dict) -> str:
    lines: list[str] = []
    if d := (row.get("desc_full") or row.get("desc")):
        lines.append(_tr_misc(d))
    ih = row.get("insurance_history") or {}
    if ih:
        lines.append("")
        lines.append("Insurance history:")
        labels = [
            ("plate_changes", "Plate changes"),
            ("owner_changes", "Owner changes"),
            ("own_damage", "Own-car damage"),
            ("opposing_damage", "Other-car damage"),
        ]
        for key, label in labels:
            lines.append(f"  - {label}: {_tr_misc(ih.get(key, '-'))}")
    if cost := row.get("cost_handling"):
        lines.append("")
        lines.append(f"Cost handling: {_tr_misc(cost)}")
    if end := (row.get("auction_end") or row.get("auction_time")):
        lines.append(f"Auction ends: {end}")
    return "\n".join(lines).strip()


def _load_cookie(cli_cookie: str | None) -> str:
    if cli_cookie:
        return cli_cookie.strip()
    if env := os.environ.get("HAPPYCAR_COOKIE", "").strip():
        return env
    fpath = Path(settings.BASE_DIR) / ".happycar_cookie"
    if fpath.exists():
        return fpath.read_text(encoding="utf-8").strip()
    return ""


class Command(BaseCommand):
    help = "Import HappyCar auction listings into a tenant's SiteCar table."

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema", required=True,
            help="Tenant schema_name to import into (never 'public').",
        )
        parser.add_argument(
            "--cookie", default=None,
            help=("Session cookie header, e.g. 'PHPSESSID=xxx; googtrans=/ko/en'. "
                  "Falls back to HAPPYCAR_COOKIE env var or .happycar_cookie file."),
        )
        parser.add_argument(
            "--pages", type=int, default=None,
            help="Cap the number of list pages fetched (useful for testing).",
        )
        parser.add_argument(
            "--workers", type=int, default=8,
            help="Parallel detail-page fetchers (default: 8).",
        )
        parser.add_argument(
            "--list-only", action="store_true",
            help="Skip detail-page fetching; import only list-page data.",
        )
        parser.add_argument(
            "--with-gallery", action="store_true",
            help="Also create SiteCarImage rows for every gallery image URL.",
        )
        parser.add_argument(
            "--download-images", action="store_true",
            help=("Download every gallery image into local/S3 storage. "
                  "Default is URL-only (no storage cost)."),
        )
        parser.add_argument(
            "--delete-missing", action="store_true",
            help=("After import, delete SiteCar rows whose external_id starts "
                  "with 'hc_' but did NOT appear in this scrape."),
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Print what would change; do not write to the DB.",
        )
        parser.add_argument(
            "--lang", default="en", choices=("en", "ar", "ko"),
            help=("Language used for title/manufacturer/model and translated "
                  "fields (default: en)."),
        )

    # ---------------- main ----------------
    def handle(self, *args, **opts):
        schema = opts["schema"]
        if schema == "public":
            raise CommandError("Refusing to import into the 'public' schema.")
        if not Tenant.objects.filter(schema_name=schema).exists():
            raise CommandError(f"Tenant with schema_name={schema!r} does not exist.")

        cookie = _load_cookie(opts["cookie"])
        if not cookie:
            self.stdout.write(self.style.WARNING(
                "No session cookie set — will fetch anonymous listings (usually "
                "fewer cars than a logged-in session sees)."
            ))

        lang = opts["lang"]
        pages = opts["pages"]
        workers = opts["workers"]
        list_only = opts["list_only"]
        with_gallery = opts["with_gallery"]
        download_images = opts["download_images"]
        delete_missing = opts["delete_missing"]
        dry_run = opts["dry_run"]

        if with_gallery and not download_images:
            self.stdout.write(self.style.WARNING(
                "--with-gallery is a no-op without --download-images "
                "(SiteCarImage.image is required). Re-run with both flags "
                "to populate SiteCarImage rows."
            ))

        self.stdout.write(self.style.HTTP_INFO(f"Scraping HappyCar list pages…"))
        rows, total = _scraper.scrape_list(
            cookie=cookie, max_pages=pages, log=self._log)
        self.stdout.write(
            f"  got {len(rows)} unique listings "
            f"(site reports total={total})"
        )

        if not list_only:
            self.stdout.write(self.style.HTTP_INFO("Fetching detail pages…"))
            _scraper.scrape_details([r["idx"] for r in rows], cookie=cookie,
                                    workers=workers, log=self._log)

        self.stdout.write(self.style.HTTP_INFO("Parsing + classifying…"))
        _scraper.enrich(rows)

        self.stdout.write(self.style.HTTP_INFO(
            f"Writing to tenant schema {schema!r}"
            f"{' (dry-run)' if dry_run else ''}…"
        ))

        stats = {"created": 0, "updated": 0, "skipped": 0, "images": 0}
        seen_external_ids: list[str] = []

        with schema_context(schema):
            for row in rows:
                ext_id = f"hc_{row['idx']}"
                seen_external_ids.append(ext_id)
                defaults = self._row_to_defaults(row, lang)
                if not defaults.get("year") or not defaults.get("manufacturer"):
                    stats["skipped"] += 1
                    continue
                if dry_run:
                    existing = SiteCar.objects.filter(external_id=ext_id).first()
                    action = "UPDATE" if existing else "CREATE"
                    self.stdout.write(
                        f"  [{action}] {ext_id} — "
                        f"{defaults.get('manufacturer')} {defaults.get('model')} "
                        f"({defaults.get('year')}) "
                        f"{defaults.get('price'):,}₩"
                    )
                    continue
                obj, created = SiteCar.objects.update_or_create(
                    external_id=ext_id, defaults=defaults)
                stats["created" if created else "updated"] += 1

                if with_gallery and row.get("images"):
                    stats["images"] += self._sync_gallery(
                        obj, row["images"], download=download_images)

                if download_images and obj.external_image_url and not obj.image:
                    self._download_main_image(obj)

        if delete_missing and not dry_run:
            with schema_context(schema):
                qs = (SiteCar.objects
                      .filter(external_id__startswith="hc_")
                      .exclude(external_id__in=seen_external_ids))
                stats["deleted"] = qs.count()
                qs.delete()

        self.stdout.write(self.style.SUCCESS(
            "Done. " + ", ".join(f"{k}={v}" for k, v in stats.items())))

    # ---------------- helpers ----------------
    def _log(self, msg: str) -> None:
        self.stdout.write(f"  {msg}")

    def _row_to_defaults(self, row: dict, lang: str) -> dict:
        make = _classify.pick(row, "make", lang) or row.get("make") or ""
        if make in ("Unknown", "غير مصنّف", "미분류"):
            make = ""
        model = _classify.pick(row, "model", lang) or row.get("model") or ""
        trim = row.get("trim") or ""

        year = row.get("year") or None
        try:
            year = int(year) if year else None
        except (TypeError, ValueError):
            year = None

        fuel = _classify.fuel_label(row.get("fuel"), lang) or (row.get("fuel") or "")
        trans = _classify.trans_label(row.get("transmission"), lang) or (row.get("transmission") or "")

        status_code = row.get("status", "")
        status = STATUS_MAP.get(status_code, "available")

        loc = row.get("storage_location") or row.get("location") or ""
        loc_translated = _locations.translate(loc, lang) if lang != "ko" else loc

        price = row.get("min_bid_price_num") or 0
        try:
            price = int(price)
        except (TypeError, ValueError):
            price = 0

        mileage = row.get("mileage_km") or 0
        try:
            mileage = int(mileage)
        except (TypeError, ValueError):
            mileage = 0

        title_bits = [make, model, trim]
        if year:
            title_bits.append(str(year))
        title = " ".join(b for b in title_bits if b).strip() or (row.get("title") or "")

        month = row.get("month") or None
        try:
            month = int(month) if month else None
        except (TypeError, ValueError):
            month = None

        engine_cc = row.get("displacement_cc") or None
        try:
            engine_cc = int(engine_cc) if engine_cc else None
        except (TypeError, ValueError):
            engine_cc = None

        ih = row.get("insurance_history") or None

        return {
            "title": title[:200],
            "description": _description(row),
            "manufacturer": make[:100] if make else "Unknown",
            "model": (model or row.get("title") or "")[:100],
            "trim": (trim or "")[:100],
            "year": year or 0,
            "month": month,
            "mileage": mileage,
            "price": price,
            "transmission": (trans or "")[:100],
            "fuel": (fuel or "")[:100],
            "engine_cc": engine_cc,
            "status": status,
            "source_status": (status_code or "")[:20],
            "location": (loc_translated or "")[:200],
            "registration_no": (row.get("registration_no") or "")[:50],
            "source_url": (row.get("detail_url") or "")[:500],
            "auction_end": _parse_auction_end(row.get("auction_end")),
            "claims_count": _claims_count(row),
            "insurance_history": ih,
            "external_image_url": row.get("thumbnail") or None,
        }

    def _sync_gallery(self, obj: SiteCar, image_urls: list[str], *, download: bool) -> int:
        """Download gallery images into SiteCarImage rows. No-op without --download-images
        because SiteCarImage.image is a required ImageField (URL-only storage isn't supported)."""
        if not download:
            return 0
        from site_cars.models import SiteCarImage
        existing_captions = set(obj.gallery.values_list("caption", flat=True))
        added = 0
        for i, url in enumerate(image_urls):
            caption = f"hc:{url.rsplit('/', 1)[-1]}"
            if caption in existing_captions:
                continue
            try:
                data = _scraper.fetch(url, cookie="")
                img = SiteCarImage(car=obj, caption=caption, order=i)
                img.image.save(caption, ContentFile(data), save=True)
                added += 1
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(f"    image download failed {url}: {exc}")
        return added

    def _download_main_image(self, obj: SiteCar) -> None:
        try:
            data = _scraper.fetch(obj.external_image_url, cookie="")
            fname = (obj.external_id or "hc") + "_thumb.jpg"
            obj.image.save(fname, ContentFile(data), save=True)
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(f"    main image download failed: {exc}")
