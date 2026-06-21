import csv
import json
import sys

import requests

from django.core.exceptions import MultipleObjectsReturned
from django.core.management.base import BaseCommand
from django.db import connection, transaction, IntegrityError

from cars.models import (
    ApiCar,
    Category,
    Manufacturer,
    CarModel,
    CarBadge,
    CarColor,
    CarSeatColor,
)
from cars.management.commands.import_encar_fast import Command as EncarFast


DEFAULT_URL = (
    "https://pub-08cf22ed84b040d8baafb1e3cad62dc7.r2.dev/kbchachacha/kb_cars.csv"
)

# Category that fully isolates KB Cha Cha Cha cars from the Encar feed. The
# Encar importer (import_encar_fast) only ever touches category_id IS NULL,
# so giving these cars a non-null category guarantees they can never be
# matched, updated, or stale-deleted by that pipeline.
KB_CATEGORY = "kbchachacha"

# How many ApiCar rows to upsert per bulk batch. Tuned for ~122k rows over a
# remote Postgres connection (Railway).
BATCH_SIZE = 1000


class Command(BaseCommand):
    help = (
        "Import KB Cha Cha Cha cars (Encar-schema CSV) into ApiCar, isolated in "
        "a dedicated 'kbchachacha' category so they never collide with the "
        "Encar importer."
    )

    # ──────────────────────────── Argparse ────────────────────────────

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            type=str,
            default=DEFAULT_URL,
            help="Direct URL to the KB Cha Cha Cha CSV (Encar schema).",
        )
        parser.add_argument(
            "--delete-stale",
            action="store_true",
            help=(
                "After import, delete kbchachacha-category cars whose lot_number "
                "was not in this CSV. SCOPED to the kbchachacha category only."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Do not write to the DB; only print intended actions.",
        )

    # ──────────────────────────── FK helpers ────────────────────────────

    def _safe_get_or_create(self, manager, defaults=None, **kwargs):
        # Respect case-insensitive unique indexes (e.g. uniq_manufacturer_name):
        # match an existing row by name__iexact first so KB's casing reuses the
        # Encar FK rows instead of colliding on insert.
        name = kwargs.get("name")
        rest = {k: v for k, v in kwargs.items() if k != "name"}
        if name is not None:
            existing = manager.filter(name__iexact=name, **rest).order_by("id").first()
            if existing:
                return existing
        try:
            obj, _ = manager.get_or_create(defaults=defaults or {}, **kwargs)
            return obj
        except MultipleObjectsReturned:
            return manager.filter(**kwargs).order_by("id").first()
        except IntegrityError:
            if name is not None:
                return manager.filter(name__iexact=name, **rest).order_by("id").first()
            return manager.filter(**kwargs).order_by("id").first()

    def _resolve_fks(self, caches, manufacturer_name, model_name, badge_name,
                     color_name, seat_color_name):
        """Resolve FK objects using in-memory dict caches.

        One get_or_create per *distinct* value (the first time it is seen),
        never per row — keeps ~122k rows fast against a remote Postgres.
        """
        manufacturer_name = (manufacturer_name or "Unknown").strip() or "Unknown"
        model_name = (model_name or "Unknown").strip() or "Unknown"
        badge_name = (badge_name or model_name).strip() or model_name
        color_name = (color_name or "Unknown").strip() or "Unknown"

        # Manufacturer (unique by name)
        manu_cache = caches.setdefault("manufacturer", {})
        if manufacturer_name not in manu_cache:
            manu_cache[manufacturer_name] = self._safe_get_or_create(
                Manufacturer.objects,
                defaults={"country": "Unknown"},
                name=manufacturer_name,
            )
        manufacturer = manu_cache[manufacturer_name]

        # CarModel (unique by name + manufacturer)
        model_cache = caches.setdefault("model", {})
        model_key = (model_name, manufacturer.id)
        if model_key not in model_cache:
            model_cache[model_key] = self._safe_get_or_create(
                CarModel.objects,
                name=model_name,
                manufacturer=manufacturer,
            )
        model = model_cache[model_key]

        # CarBadge (keyed by name + model)
        badge_cache = caches.setdefault("badge", {})
        badge_key = (badge_name, model.id)
        if badge_key not in badge_cache:
            badge_cache[badge_key] = self._safe_get_or_create(
                CarBadge.objects,
                name=badge_name,
                model=model,
            )
        badge = badge_cache[badge_key]

        # CarColor (keyed by name)
        color_cache = caches.setdefault("color", {})
        if color_name not in color_cache:
            color_cache[color_name] = self._safe_get_or_create(
                CarColor.objects,
                name=color_name,
            )
        color = color_cache[color_name]

        # CarSeatColor (optional — only when present)
        seat_color = None
        seat_color_name = (seat_color_name or "").strip()
        if seat_color_name:
            seat_cache = caches.setdefault("seat_color", {})
            if seat_color_name not in seat_cache:
                seat_cache[seat_color_name] = self._safe_get_or_create(
                    CarSeatColor.objects,
                    name=seat_color_name,
                )
            seat_color = seat_cache[seat_color_name]

        return manufacturer, model, badge, color, seat_color

    def _parse_images(self, fields_images):
        """images in the CSV is a JSON-array string; _row_to_fields may already
        have parsed it into a list. Guard everything → [] on failure."""
        val = fields_images
        if isinstance(val, list):
            return val
        if not val:
            return []
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []

    # ──────────────────────────── Download ────────────────────────────

    def _download_csv_stream(self, url):
        try:
            csv.field_size_limit(1024 * 1024 * 1024)
        except OverflowError:
            csv.field_size_limit(sys.maxsize)

        self.stdout.write(f"Fetching KB CSV: {url}")
        resp = requests.get(url, timeout=60, stream=True)
        resp.raise_for_status()
        if not resp.encoding:
            resp.encoding = "utf-8-sig"
        return resp

    def _iter_rows(self, resp):
        # utf-8-sig strips the BOM if present.
        lines = (line.decode("utf-8-sig") for line in resp.iter_lines() if line is not None)
        reader = csv.DictReader(lines)
        for row in reader:
            yield row

    # ──────────────────────────── Bulk upsert ────────────────────────────

    # ApiCar columns written on update (excludes auto/pk fields and car_id which
    # is the stable namespaced key set once on create).
    _UPDATE_FIELDS = [
        "title", "manufacturer", "category", "model", "badge", "color",
        "seat_color", "lot_number", "year", "mileage", "price", "fuel",
        "transmission", "model_version", "model_year_range", "engine_group",
        "trim_detail", "address", "images", "seat_count", "vin", "image",
    ]

    def _build_car_kwargs(self, cat, ln, car_id, fields, manufacturer, model,
                          badge, color, seat_color):
        title = f"{fields['year']} {manufacturer.name} {model.name}".strip()
        return {
            "category": cat,
            "manufacturer": manufacturer,
            "model": model,
            "badge": badge,
            "color": color,
            "seat_color": seat_color,
            "lot_number": ln,
            "car_id": car_id,
            "year": fields["year"],
            "mileage": fields["mileage"],
            "price": fields["price"],
            "fuel": fields["fuel"],
            "transmission": fields["transmission"],
            "model_version": fields["model_version"],
            "model_year_range": fields["model_year_range"],
            "engine_group": fields["engine_group"],
            "trim_detail": fields["trim_detail"],
            "address": fields.get("address") or "",
            "images": self._parse_images(fields.get("images")),
            "seat_count": fields.get("seat_count") or "",
            "vin": fields.get("vin") or ln,
            "image": fields.get("image"),
            "title": title[:100],
        }

    def _flush_batch(self, cat, batch, caches, dry_run, counters):
        """Upsert one batch of prepared field-dicts (mirrors import_auction_json
        pass 2 + pass 3): preload existing rows for this category, update those
        in place via bulk_update, bulk_create the rest."""
        if not batch:
            return []

        lns = [b["lot_number"] for b in batch]
        existing = {
            c.lot_number: c
            for c in ApiCar.objects.filter(category=cat, lot_number__in=lns)
        }

        to_create = []
        to_update = []
        new_lns = []

        for fields in batch:
            ln = fields["lot_number"]
            car_id = ln[:20]
            manufacturer, model, badge, color, seat_color = self._resolve_fks(
                caches,
                fields["manufacturer_name"],
                fields["model_name"],
                fields["badge_name"],
                fields["color_name"],
                fields["seat_color_name"],
            )
            kwargs = self._build_car_kwargs(
                cat, ln, car_id, fields, manufacturer, model, badge, color,
                seat_color,
            )

            if ln in existing:
                car = existing[ln]
                for key, value in kwargs.items():
                    if key == "car_id":
                        continue  # keep the original stable car_id
                    setattr(car, key, value)
                to_update.append(car)
                counters["updated"] += 1
            else:
                to_create.append(ApiCar(**kwargs))
                new_lns.append(ln)
                counters["created"] += 1

        if dry_run:
            return new_lns

        with transaction.atomic():
            if to_update:
                ApiCar.objects.bulk_update(
                    to_update, self._UPDATE_FIELDS, batch_size=BATCH_SIZE
                )
            if to_create:
                ApiCar.objects.bulk_create(
                    to_create, batch_size=BATCH_SIZE, ignore_conflicts=True
                )

        return new_lns

    def _backfill_slugs(self):
        """Backfill empty slugs for bulk_created rows (save() bypassed). Same
        raw SQL approach as import_auction_json."""
        with connection.cursor() as cur:
            cur.execute(
                """
                UPDATE cars_apicar
                SET slug = CONCAT(
                    COALESCE(CAST(year AS TEXT), ''), '-',
                    LOWER(REGEXP_REPLACE(
                        COALESCE((SELECT name FROM cars_manufacturer WHERE id = manufacturer_id), ''),
                        '[^a-zA-Z0-9]+', '-', 'g'
                    )), '-',
                    LOWER(REGEXP_REPLACE(
                        COALESCE((SELECT name FROM cars_carmodel WHERE id = model_id), ''),
                        '[^a-zA-Z0-9]+', '-', 'g'
                    )), '-',
                    CAST(id AS TEXT)
                )
                WHERE slug IS NULL OR slug = ''
                """
            )

    def _delete_stale(self, cat, seen_lns, dry_run):
        """Delete kbchachacha-category cars not seen in this CSV. SCOPED to the
        kbchachacha category — never touches other categories or Encar cars."""
        qs = ApiCar.objects.filter(category=cat).exclude(lot_number__in=seen_lns)
        count = qs.count()
        if dry_run:
            self.stdout.write(
                f"[DRY-RUN] Would delete {count} stale kbchachacha cars."
            )
            return count
        deleted, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Stale deletion done. Deleted: {count}"))
        return count

    # ──────────────────────────── Main ────────────────────────────

    def handle(self, *args, **options):
        url = options["url"]
        delete_stale = options.get("delete_stale", False)
        dry_run = options.get("dry_run", False)

        cat, _ = Category.objects.get_or_create(name=KB_CATEGORY)

        # Reuse the Encar row→fields mapping verbatim.
        ef = EncarFast()

        caches = {}
        counters = {"created": 0, "updated": 0}
        seen_lns = set()
        new_lns_all = []
        batch = []
        processed = 0

        resp = self._download_csv_stream(url)
        try:
            for row in self._iter_rows(resp):
                processed += 1
                fields = ef._row_to_fields(row)
                if not fields["lot_number"]:
                    continue

                # Namespace the lot so KB lots can never collide with Encar lots.
                ln = "kb-" + fields["lot_number"]
                fields["lot_number"] = ln
                seen_lns.add(ln)
                batch.append(fields)

                if len(batch) >= BATCH_SIZE:
                    new_lns_all.extend(
                        self._flush_batch(cat, batch, caches, dry_run, counters)
                    )
                    batch = []

                if processed % 5000 == 0:
                    self.stdout.write(
                        f"Processed {processed} rows... "
                        f"Created: {counters['created']}, Updated: {counters['updated']}"
                    )
        finally:
            resp.close()

        # Leftover.
        if batch:
            new_lns_all.extend(
                self._flush_batch(cat, batch, caches, dry_run, counters)
            )

        # Slug backfill for newly-created rows.
        if not dry_run and new_lns_all:
            self._backfill_slugs()

        deleted = 0
        if delete_stale:
            deleted = self._delete_stale(cat, seen_lns, dry_run)

        summary = (
            f"Done. CSV rows: {processed}, Created: {counters['created']}, "
            f"Updated: {counters['updated']}, Deleted (stale): {deleted}"
        )
        if dry_run:
            summary = "[DRY-RUN] " + summary
        self.stdout.write(self.style.SUCCESS(summary))
