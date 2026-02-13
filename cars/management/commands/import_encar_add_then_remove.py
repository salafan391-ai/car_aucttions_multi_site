import csv
import io
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import MultipleObjectsReturned
from django.db import transaction

from core.models import (
    ApiCar,
    Manufacturer,
    CarModel,
    CarBadge,
    CarColor,
    CarSeatColor,
)


class Command(BaseCommand):
    help = "Import Encar: add NEW cars from active_offer.csv only (no updates), then delete cars listed in removed_offer.csv. Optimized for low memory."

    # ------------- CLI -------------
    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, help="Date in YYYY-MM-DD. Defaults to today's UTC date.")
        parser.add_argument(
            "--host",
            type=str,
            default=(os.getenv("ENCAR_HOST") or os.getenv("ENCAR_AUTObASE_HOST")),
            help="Autobase host (env: ENCAR_HOST; fallback: ENCAR_AUTObASE_HOST)",
        )
        parser.add_argument(
            "--username",
            type=str,
            default=(os.getenv("ENCAR_USER") or os.getenv("ENCAR_AUTObASE_USER")),
            help="Basic auth username (env: ENCAR_USER; fallback: ENCAR_AUTObASE_USER)",
        )
        parser.add_argument(
            "--password",
            type=str,
            default=(os.getenv("ENCAR_PASS") or os.getenv("ENCAR_AUTObASE_PASS")),
            help="Basic auth password (env: ENCAR_PASS; fallback: ENCAR_AUTObASE_PASS)",
        )
        parser.add_argument("--dry-run", action="store_true", help="Do not write changes to DB")
        parser.add_argument("--progress", action="store_true", help="Print periodic progress")
        parser.add_argument("--progress-every", type=int, default=5000, help="Progress frequency in rows")
        parser.add_argument("--max-rows", type=int, default=0, help="If > 0, stop after this many rows")
        parser.add_argument("--chunk-size", type=int, default=1000, help="Rows per processing chunk for active feed")
        parser.add_argument("--create-batch-size", type=int, default=500, help="Batch size for bulk_create")
        parser.add_argument("--delete-batch-size", type=int, default=3000, help="Batch size for removed deletions")
        parser.add_argument("--skip-removed", action="store_true", help="Skip processing removed file")

    # ------------- helpers -------------
    def _utc_today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _build_urls(self, host: str, date_str: str) -> Tuple[str, str]:
        base = host.rstrip("/") + f"/encar/{date_str}"
        return (f"{base}/active_offer.csv", f"{base}/removed_offer.csv")

    def _download_csv_stream(self, url: str, username: str, password: str) -> Optional[requests.Response]:
        try:
            resp = requests.get(url, auth=(username, password), timeout=60, stream=True)
            if resp.status_code == 404:
                self.stdout.write(self.style.WARNING(f"CSV not found: {url}"))
                resp.close()
                return None
            resp.raise_for_status()
            if not resp.encoding:
                resp.encoding = "utf-8"
            return resp
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Failed to download {url}: {e}"))
            return None

    def _to_int(self, val: Any, default: int = 0, max_value: Optional[int] = None) -> int:
        try:
            if val in (None, "", "null", "None"):
                return default
            i = int(float(str(val).strip()))
            if max_value is not None:
                i = max(0, min(max_value, i))
            return i
        except Exception:
            return default

    def _parse_json_safe(self, s: str):
        if not s:
            return None
        s = s.strip()
        try:
            return json.loads(s)
        except Exception:
            if "," in s:
                return [x.strip() for x in s.split(",") if x.strip()]
            return s

    def _first_image(self, images_field: str) -> Optional[str]:
        if not images_field:
            return None
        parsed = self._parse_json_safe(images_field)
        if isinstance(parsed, list) and parsed:
            return str(parsed[0])
        if isinstance(parsed, str):
            if "," in parsed:
                return parsed.split(",")[0].strip()
            return parsed
        return None

    def _safe_get_or_create(self, manager, defaults=None, **kwargs):
        try:
            obj, _ = manager.get_or_create(defaults=defaults or {}, **kwargs)
            return obj
        except MultipleObjectsReturned:
            return manager.filter(**kwargs).order_by('id').first()

    def _get_or_create_related(self, caches: Dict[str, Dict], manufacturer_name: str, model_name: str, badge_name: str, color_name: str, seat_color_name: Optional[str]):
        manu_cache = caches.setdefault("manufacturer", {})
        if manufacturer_name not in manu_cache:
            manu_cache[manufacturer_name] = self._safe_get_or_create(
                Manufacturer.objects,
                defaults={"country": "Unknown"},
                name=manufacturer_name,
            )
        manufacturer = manu_cache[manufacturer_name]

        model_cache = caches.setdefault("model", {})
        model_key = (model_name, manufacturer.id)
        if model_key not in model_cache:
            model_cache[model_key] = self._safe_get_or_create(
                CarModel.objects,
                name=model_name,
                manufacturer=manufacturer,
            )
        model = model_cache[model_key]

        badge_cache = caches.setdefault("badge", {})
        badge_key = (badge_name or model_name, model.id)
        if badge_key not in badge_cache:
            badge_cache[badge_key] = self._safe_get_or_create(
                CarBadge.objects,
                name=(badge_name or model_name),
                model=model,
            )
        badge = badge_cache[badge_key]

        color_cache = caches.setdefault("color", {})
        if color_name not in color_cache:
            color_cache[color_name] = self._safe_get_or_create(
                CarColor.objects,
                name=color_name,
            )
        color = color_cache[color_name]

        seat_cache = caches.setdefault("seat_color", {})
        seat_color_obj = None
        if seat_color_name:
            if seat_color_name not in seat_cache:
                seat_cache[seat_color_name] = self._safe_get_or_create(
                    CarSeatColor.objects,
                    name=seat_color_name,
                )
            seat_color_obj = seat_cache[seat_color_name]

        return manufacturer, model, badge, color, seat_color_obj

    def _row_to_fields(self, row: Dict[str, str]) -> Dict[str, Any]:
        n = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        manufacturer_name = n.get("mark") or "Unknown"
        model_name = n.get("model") or "Unknown"
        badge_name = n.get("configuration") or n.get("complectation") or model_name
        lot_number = n.get("inner_id") or n.get("id") or ""
        year = self._to_int(n.get("year"), default=0, max_value=2147483647)
        mileage = self._to_int(n.get("km_age"), default=0, max_value=9223372036854775807)
        price = self._to_int(n.get("price"), default=0, max_value=9223372036854775807)
        power = self._to_int(n.get("displacement") or n.get("dispacement"), default=0, max_value=2147483647)
        price_kw = price * 10000
        transmission = n.get("transmission_type") or "Unknown"
        body_type = n.get("body_type")
        fuel = n.get("engine_type")
        color_name = n.get("color") or "Unknown"
        seat_color_name = n.get("seatColor")
        drive_wheel = n.get("prep_drive_type") or ""
        seat_count = n.get("seatCount") or ""
        raw_images = n.get("images") or ""
        address = n.get("address") or ""
        parsed_images = self._parse_json_safe(raw_images)
        images_list = None
        if isinstance(parsed_images, list):
            images_list = [str(x) for x in parsed_images if x]
        elif isinstance(parsed_images, str):
            if parsed_images:
                images_list = [x.strip() for x in parsed_images.split(",") if x.strip()]
        image = self._first_image(raw_images)
        title = f"{manufacturer_name} {model_name} {badge_name} {year}".strip()
        options = self._parse_json_safe(n.get("options") or "")
        extra = self._parse_json_safe(n.get("extra") or "")
        vin = n.get("inner_id") or n.get("id") or ""
        return {
            "manufacturer_name": manufacturer_name,
            "model_name": model_name,
            "badge_name": badge_name,
            "lot_number": lot_number,
            "year": year,
            "mileage": mileage,
            "price": price_kw,
            "power": power,
            "transmission": transmission,
            "body_type": body_type,
            "fuel": fuel,
            "color_name": color_name,
            "seat_color_name": seat_color_name,
            "image": image,
            "images": images_list,
            "title": title,
            "options": options,
            "extra": extra,
            "vin": vin,
            "drive_wheel": drive_wheel,
            "seat_count": seat_count,
            "address": address,
        }

    # ------------- iterators -------------
    def _iter_csv_stream(self, resp: requests.Response) -> Iterable[Dict[str, str]]:
        raw_iter = resp.iter_lines(decode_unicode=False)
        line_iter = (
            (line.decode(resp.encoding or "utf-8", errors="replace") if isinstance(line, (bytes, bytearray)) else line)
            for line in raw_iter if line is not None
        )
        # Increase CSV field size limit to handle very large fields
        try:
            csv.field_size_limit(1024 * 1024 * 1024)  # 1GB
        except OverflowError:
            csv.field_size_limit(sys.maxsize)
        reader = csv.DictReader(line_iter, delimiter='|')
        for row in reader:
            yield row

    # ------------- processing -------------
    def _process_active_add_only(self, resp: requests.Response, *, chunk_size: int, create_batch_size: int, progress: bool = False, progress_every: int = 5000, max_rows: int = 0, dry_run: bool = False) -> int:
        created = 0
        processed = 0
        caches: Dict[str, Dict] = {}
        rows_buffer: List[Dict[str, Any]] = []

        def flush(rows: List[Dict[str, Any]]):
            nonlocal created
            if not rows:
                return
            lot_numbers = [r["lot_number"] for r in rows if r["lot_number"]]
            if not lot_numbers:
                return
            # find existing (store first id per lot_number)
            existing_map: Dict[str, int] = {}
            for r in (
                ApiCar.objects.filter(lot_number__in=lot_numbers).order_by('id').values('id', 'lot_number')
            ):
                ln = r['lot_number']
                if ln not in existing_map:
                    existing_map[ln] = r['id']

            to_create: List[ApiCar] = []
            for f in rows:
                ln = f["lot_number"]
                if ln in existing_map:
                    continue  # skip updates entirely
                manufacturer, model, badge, color, seat_color = self._get_or_create_related(
                    caches,
                    f["manufacturer_name"], f["model_name"], f["badge_name"], f["color_name"], f["seat_color_name"],
                )
                if not dry_run:
                    to_create.append(ApiCar(
                        title=f["title"], image=f["image"], images=f["images"],
                        manufacturer=manufacturer, vin=f["vin"] or ln, lot_number=ln,
                        model=model, year=f["year"], badge=badge, color=color, seat_color=seat_color,
                        transmission=f["transmission"], engine=None, body_type=f["body_type"], power=f["power"],
                        price=f["price"], mileage=f["mileage"], drive_wheel=f["drive_wheel"], seat_count=f["seat_count"],
                        fuel=f["fuel"], is_leasing=False, extra_features=f["extra"], options=f["options"],
                        address=f["address"],
                    ))
                    created += 1
            if not dry_run and to_create:
                with transaction.atomic():
                    ApiCar.objects.bulk_create(to_create, ignore_conflicts=True, batch_size=create_batch_size)

        for row in self._iter_csv_stream(resp):
            processed += 1
            fields = self._row_to_fields(row)
            if not fields["lot_number"]:
                continue
            rows_buffer.append(fields)
            if len(rows_buffer) >= chunk_size:
                flush(rows_buffer)
                rows_buffer.clear()
            if progress and processed % max(1, progress_every) == 0:
                self.stdout.write(f"Processed {processed} rows... Created: {created}")
            if max_rows and processed >= max_rows:
                break
        if rows_buffer:
            flush(rows_buffer)
        return created

    def _process_removed_delete(self, resp: requests.Response, *, delete_batch_size: int, progress: bool = False, progress_every: int = 5000, max_rows: int = 0, dry_run: bool = False) -> int:
        removed = 0
        processed = 0
        batch: List[str] = []
        for row in self._iter_csv_stream(resp):
            processed += 1
            ln = (row.get("inner_id") or row.get("id") or "").strip()
            if not ln:
                continue
            batch.append(ln)
            if len(batch) >= delete_batch_size:
                if not dry_run:
                    qs = ApiCar.objects.filter(lot_number__in=batch)
                    cnt = qs.count()
                    if cnt:
                        qs.delete()
                    removed += cnt
                batch.clear()
            if progress and processed % max(1, progress_every) == 0:
                self.stdout.write(f"Processed {processed} removed rows... Deleted so far: {removed}")
            if max_rows and processed >= max_rows:
                break
        if batch:
            if not dry_run:
                qs = ApiCar.objects.filter(lot_number__in=batch)
                cnt = qs.count()
                if cnt:
                    qs.delete()
                removed += cnt
        return removed

    # ------------- handle -------------
    def handle(self, *args, **options):
        date_str = options.get("date") or self._utc_today()
        host = options.get("host")
        username = options.get("username")
        password = options.get("password")
        dry_run = options.get("dry_run", False)
        progress = options.get("progress", False)
        progress_every = options.get("progress_every", 5000)
        max_rows = options.get("max_rows", 0)
        chunk_size = options.get("chunk_size", 1000)
        create_batch_size = options.get("create_batch_size", 500)
        delete_batch_size = options.get("delete_batch_size", 3000)
        skip_removed = options.get("skip_removed", False)

        missing = []
        if not host:
            missing.append("--host or ENCAR_HOST/ENCAR_AUTObASE_HOST")
        if not username:
            missing.append("--username or ENCAR_USER/ENCAR_AUTObASE_USER")
        if not password:
            missing.append("--password or ENCAR_PASS/ENCAR_AUTObASE_PASS")
        if missing:
            raise CommandError(
                "Missing required parameters: " + ", ".join(missing)
            )

        active_url, removed_url = self._build_urls(host, date_str)
        self.stdout.write(f"Fetching active: {active_url}")
        active_resp = self._download_csv_stream(active_url, username, password)

        total_created = 0
        total_removed = 0

        if active_resp:
            created = self._process_active_add_only(
                active_resp,
                chunk_size=chunk_size,
                create_batch_size=create_batch_size,
                progress=progress,
                progress_every=progress_every,
                max_rows=max_rows,
                dry_run=dry_run,
            )
            total_created += created
            self.stdout.write(self.style.SUCCESS(f"Active processed. Created: {created}"))
            active_resp.close()
        else:
            self.stdout.write(self.style.WARNING("No active_offer.csv to process."))

        if not skip_removed:
            self.stdout.write(f"Fetching removed: {removed_url}")
            removed_resp = self._download_csv_stream(removed_url, username, password)
            if removed_resp:
                removed = self._process_removed_delete(
                    removed_resp,
                    delete_batch_size=delete_batch_size,
                    progress=progress,
                    progress_every=progress_every,
                    max_rows=max_rows,
                    dry_run=dry_run,
                )
                total_removed += removed
                self.stdout.write(self.style.SUCCESS(f"Removed processed. Deleted: {removed}"))
                removed_resp.close()
            else:
                self.stdout.write(self.style.WARNING("No removed_offer.csv to process."))

        summary = f"Done for {date_str}. Created: {total_created}, Deleted: {total_removed}"
        if dry_run:
            summary = "[DRY-RUN] " + summary
        self.stdout.write(self.style.SUCCESS(summary))
