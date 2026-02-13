import csv
import io
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

import requests
from django.core.management.base import BaseCommand
from django.db import transaction
from django.core.exceptions import MultipleObjectsReturned

from core.models import (
    ApiCar,
    Manufacturer,
    CarModel,
    CarBadge,
    CarColor,
    CarSeatColor,
)


class Command(BaseCommand):
    help = "Import Encar daily CSV exports (active and removed) from autobase and sync into ApiCar"

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            help="Date in YYYY-MM-DD for the export folder (UTC). Defaults to today's UTC date.",
        )
        parser.add_argument(
            "--host",
            type=str,
            default=os.getenv("ENCAR_HOST"),
            help="Base host for autobase (env: ENCAR_HOST)",
        )
        parser.add_argument(
            "--username",
            type=str,
            default=os.getenv("ENCAR_USER"),
            help="Basic auth username (env: ENCAR_USER)",
        )
        parser.add_argument(
            "--password",
            type=str,
            default=os.getenv("ENCAR_PASS"),
            help="Basic auth password (env: ENCAR_PASS)",
        )
        parser.add_argument(
            "--skip-removed",
            action="store_true",
            help="Skip processing removed_offer.csv",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Do not write changes to DB; only print intended actions",
        )
        parser.add_argument(
            "--progress",
            action="store_true",
            help="Print periodic progress while processing rows",
        )
        parser.add_argument(
            "--progress-every",
            type=int,
            default=5000,
            help="Progress print frequency in rows (default 5000)",
        )
        parser.add_argument(
            "--max-rows",
            type=int,
            default=0,
            help="If > 0, stop after processing this many rows (useful for quick checks)",
        )

    def _utc_today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _build_urls(self, host: str, date_str: str) -> Tuple[str, str]:
        base = host.rstrip("/") + f"/encar/{date_str}"
        return (
            f"{base}/active_offer.csv",
            f"{base}/removed_offer.csv",
        )

    def _download_csv_stream(self, url: str, username: str, password: str) -> Optional[requests.Response]:
        try:
            resp = requests.get(url, auth=(username, password), timeout=60, stream=True)
            if resp.status_code == 404:
                self.stdout.write(self.style.WARNING(f"CSV not found: {url}"))
                resp.close()
                return None
            resp.raise_for_status()
            # Ensure we have an encoding for unicode decoding later
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
            # Try to interpret as comma-separated values
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
            # If it's a single URL or comma-separated, take first
            if "," in parsed:
                return parsed.split(",")[0].strip()
            return parsed
        return None

    def _safe_get_or_create(self, manager, defaults=None, **kwargs):
        """Get or create, but if duplicates already exist, return the first one instead of raising.
        This avoids crashes when legacy data has duplicates for the same unique key."""
        try:
            obj, _ = manager.get_or_create(defaults=defaults or {}, **kwargs)
            return obj
        except MultipleObjectsReturned:
            return manager.filter(**kwargs).order_by('id').first()

    def _get_or_create_related(self, caches: Dict[str, Dict], manufacturer_name: str, model_name: str, badge_name: str, color_name: str, seat_color_name: Optional[str]):
        # Manufacturer
        manu_cache = caches.setdefault("manufacturer", {})
        if manufacturer_name not in manu_cache:
            manu_cache[manufacturer_name] = self._safe_get_or_create(
                Manufacturer.objects,
                defaults={"country": "Unknown"},
                name=manufacturer_name,
            )
        manufacturer = manu_cache[manufacturer_name]

        # Model
        model_cache = caches.setdefault("model", {})
        model_key = (model_name, manufacturer.id)
        if model_key not in model_cache:
            model_cache[model_key] = self._safe_get_or_create(
                CarModel.objects,
                name=model_name,
                manufacturer=manufacturer,
            )
        model = model_cache[model_key]

        # Badge
        badge_cache = caches.setdefault("badge", {})
        badge_key = (badge_name or model_name, model.id)
        if badge_key not in badge_cache:
            badge_cache[badge_key] = self._safe_get_or_create(
                CarBadge.objects,
                name=(badge_name or model_name),
                model=model,
            )
        badge = badge_cache[badge_key]

        # Color
        color_cache = caches.setdefault("color", {})
        if color_name not in color_cache:
            color_cache[color_name] = self._safe_get_or_create(
                CarColor.objects,
                name=color_name,
            )
        color = color_cache[color_name]

        # Seat Color (optional)
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
        # Normalize keys
        norm = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}

        manufacturer_name = norm.get("mark") or "Unknown"
        model_name = norm.get("model") or "Unknown"
        badge_name = norm.get("configuration") or norm.get("complectation") or model_name

        lot_number = norm.get("inner_id") or norm.get("id") or ""

        year = self._to_int(norm.get("year"), default=0, max_value=2147483647)
        mileage = self._to_int(norm.get("km_age"), default=0, max_value=9223372036854775807)
        price = self._to_int(norm.get("price"), default=0, max_value=9223372036854775807)
        power = self._to_int(norm.get("displacement") or norm.get("dispacement"), default=0, max_value=2147483647)
        price_kw = price*10000

        transmission = norm.get("transmission_type") or "Unknown"
        body_type = norm.get("body_type")
        fuel = norm.get("engine_type")
        color_name = norm.get("color") or "Unknown"
        seat_color_name = norm.get("seatColor")
        drive_wheel = norm.get("prep_drive_type") or ""
        seat_count = norm.get("seatCount") or ""


        raw_images = norm.get("images") or ""
        # Parse images column into a list where possible
        parsed_images = self._parse_json_safe(raw_images)
        images_list = None
        if isinstance(parsed_images, list):
            images_list = [str(x) for x in parsed_images if x]
        elif isinstance(parsed_images, str):
            # Fallback: comma-separated string
            if parsed_images:
                images_list = [x.strip() for x in parsed_images.split(",") if x.strip()]
        image = self._first_image(raw_images)

        # Title synth since CSV lacks title field
        title = f"{manufacturer_name} {model_name} {badge_name} {year}".strip()

        # Options / extra
        options = self._parse_json_safe(norm.get("options") or "")
        extra = self._parse_json_safe(norm.get("extra") or "")
        

        # No VIN in CSV; use inner_id as VIN surrogate to satisfy non-null constraint
        vin = norm.get("inner_id") or norm.get("id") or ""

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
            }

    def _process_active(self, csv_text: str, dry_run: bool = False) -> Tuple[int, int]:
        created = 0
        updated = 0

        reader = csv.DictReader(io.StringIO(csv_text), delimiter='|')
        caches: Dict[str, Dict] = {}
        batch_new = []

        for row in reader:
            fields = self._row_to_fields(row)

            if not fields["lot_number"]:
                continue

            manufacturer, model, badge, color, seat_color = self._get_or_create_related(
                caches,
                fields["manufacturer_name"],
                fields["model_name"],
                fields["badge_name"],
                fields["color_name"],
                fields["seat_color_name"],
            )

            # Upsert by lot_number primarily; if exists, update; else create
            existing = ApiCar.objects.filter(lot_number=fields["lot_number"]).first()
            if existing:
                updated += 1
                if not dry_run:
                    existing.title = fields["title"]
                    existing.image = fields["image"]
                    existing.images = fields["images"]
                    existing.manufacturer = manufacturer
                    existing.vin = fields["vin"] or existing.vin or fields["lot_number"]
                    existing.lot_number = fields["lot_number"]
                    existing.model = model
                    existing.year = fields["year"]
                    existing.badge = badge
                    existing.color = color
                    existing.seat_color = seat_color
                    existing.transmission = fields["transmission"]
                    existing.engine = None
                    existing.body_type = fields["body_type"]
                    existing.power = fields["power"]
                    existing.price = fields["price"]
                    existing.mileage = fields["mileage"]
                    existing.drive_wheel = fields["drive_wheel"]
                    existing.seat_count = fields["seat_count"]
                    existing.fuel = fields["fuel"]
                    existing.is_leasing = False
                    existing.extra_features = fields["extra"]
                    existing.options = fields["options"]
                    existing.save()
            else:
                created += 1
                if not dry_run:
                    batch_new.append(
                        ApiCar(
                            title=fields["title"],
                            image=fields["image"],
                            images=fields["images"],
                            manufacturer=manufacturer,
                            vin=fields["vin"] or fields["lot_number"],
                            lot_number=fields["lot_number"],
                            model=model,
                            year=fields["year"],
                            badge=badge,
                            color=color,
                            seat_color=seat_color,
                            transmission=fields["transmission"],
                            engine=None,
                            body_type=fields["body_type"],
                            power=fields["power"],
                            price=fields["price"],
                            mileage=fields["mileage"],
                            drive_wheel=fields["drive_wheel"],
                            seat_count=fields["seat_count"],
                            fuel=fields["fuel"],
                            is_leasing=False,
                            extra_features=fields["extra"],
                            options=fields["options"],
                        )
                    )

        if not dry_run and batch_new:
            with transaction.atomic():
                ApiCar.objects.bulk_create(batch_new, ignore_conflicts=True)

        return created, updated

    def _process_removed(self, csv_text: str, dry_run: bool = False) -> int:
        removed = 0
        reader = csv.DictReader(io.StringIO(csv_text), delimiter='|')
        for row in reader:
            lot_number = (row.get("inner_id") or row.get("id") or "").strip()
            if not lot_number:
                continue
            qs = ApiCar.objects.filter(lot_number=lot_number)
            if qs.exists():
                removed += qs.count()
                if not dry_run:
                    qs.delete()
        return removed

    def _process_active_stream(self, resp: requests.Response, dry_run: bool = False, *, progress: bool = False, progress_every: int = 5000, max_rows: int = 0) -> Tuple[int, int]:
        created = 0
        updated = 0
        processed = 0
        # Ensure text iteration; decode bytes defensively to str
        raw_iter = resp.iter_lines(decode_unicode=False)
        line_iter = (
            (line.decode(resp.encoding or "utf-8", errors="replace") if isinstance(line, (bytes, bytearray)) else line)
            for line in raw_iter if line is not None
        )
        reader = csv.DictReader(line_iter, delimiter='|')
        caches: Dict[str, Dict] = {}
        batch_new = []

        for row in reader:
            processed += 1
            fields = self._row_to_fields(row)

            if not fields["lot_number"]:
                continue

            manufacturer, model, badge, color, seat_color = self._get_or_create_related(
                caches,
                fields["manufacturer_name"],
                fields["model_name"],
                fields["badge_name"],
                fields["color_name"],
                fields["seat_color_name"],
            )

            existing = ApiCar.objects.filter(lot_number=fields["lot_number"]).first()
            if existing:
                updated += 1
                if not dry_run:
                    existing.title = fields["title"]
                    existing.image = fields["image"]
                    existing.images = fields["images"]
                    existing.manufacturer = manufacturer
                    existing.vin = fields["vin"] or existing.vin or fields["lot_number"]
                    existing.lot_number = fields["lot_number"]
                    existing.model = model
                    existing.year = fields["year"]
                    existing.badge = badge
                    existing.color = color
                    existing.seat_color = seat_color
                    existing.transmission = fields["transmission"]
                    existing.engine = None
                    existing.body_type = fields["body_type"]
                    existing.power = fields["power"]
                    existing.price = fields["price"]
                    existing.mileage = fields["mileage"]
                    existing.drive_wheel = fields["drive_wheel"]
                    existing.seat_count = fields["seat_count"]
                    existing.fuel = fields["fuel"]
                    existing.is_leasing = False
                    existing.extra_features = fields["extra"]
                    existing.options = fields["options"]
                    existing.save()
            else:
                created += 1
                if not dry_run:
                    batch_new.append(
                        ApiCar(
                            title=fields["title"],
                            image=fields["image"],
                            images=fields["images"],
                            manufacturer=manufacturer,
                            vin=fields["vin"] or fields["lot_number"],
                            lot_number=fields["lot_number"],
                            model=model,
                            year=fields["year"],
                            badge=badge,
                            color=color,
                            seat_color=seat_color,
                            transmission=fields["transmission"],
                            engine=None,
                            body_type=fields["body_type"],
                            power=fields["power"],
                            price=fields["price"],
                            mileage=fields["mileage"],
                            drive_wheel=fields["drive_wheel"],
                            seat_count=fields["seat_count"],
                            fuel=fields["fuel"],
                            is_leasing=False,
                            extra_features=fields["extra"],
                            options=fields["options"],
                        )
                    )

            # Periodically flush to DB to control memory
            if not dry_run and len(batch_new) >= 1000:
                with transaction.atomic():
                    ApiCar.objects.bulk_create(batch_new, ignore_conflicts=True)
                batch_new.clear()

            # Progress output
            if progress and processed % max(1, progress_every) == 0:
                self.stdout.write(f"Processed {processed} rows... Created: {created}, Updated: {updated}")

            # Optional early stop
            if max_rows and processed >= max_rows:
                break

        if not dry_run and batch_new:
            with transaction.atomic():
                ApiCar.objects.bulk_create(batch_new, ignore_conflicts=True)

        return created, updated

    def _process_removed_stream(self, resp: requests.Response, dry_run: bool = False, *, progress: bool = False, progress_every: int = 5000, max_rows: int = 0) -> int:
        removed = 0
        processed = 0
        raw_iter = resp.iter_lines(decode_unicode=False)
        line_iter = (
            (line.decode(resp.encoding or "utf-8", errors="replace") if isinstance(line, (bytes, bytearray)) else line)
            for line in raw_iter if line is not None
        )
        reader = csv.DictReader(line_iter, delimiter='|')
        for row in reader:
            processed += 1
            lot_number = (row.get("inner_id") or row.get("id") or "").strip()
            if not lot_number:
                continue
            qs = ApiCar.objects.filter(lot_number=lot_number)
            if qs.exists():
                removed += qs.count()
                if not dry_run:
                    qs.delete()
            if progress and processed % max(1, progress_every) == 0:
                self.stdout.write(f"Processed {processed} removed rows... Deleted so far: {removed}")
            if max_rows and processed >= max_rows:
                break
        return removed

    def handle(self, *args, **options):
        date_str = options.get("date") or self._utc_today()
        host = options.get("host")
        username = options.get("username")
        password = options.get("password")
        skip_removed = options.get("skip_removed", False)
        dry_run = options.get("dry_run", False)
        progress = options.get("progress", False)
        progress_every = options.get("progress_every", 5000)
        max_rows = options.get("max_rows", 0)

        active_url, removed_url = self._build_urls(host, date_str)
        self.stdout.write(f"Fetching active: {active_url}")
        active_resp = self._download_csv_stream(active_url, username, password)

        total_created = total_updated = total_removed = 0

        if active_resp:
            created, updated = self._process_active_stream(
                active_resp,
                dry_run=dry_run,
                progress=progress,
                progress_every=progress_every,
                max_rows=max_rows,
            )
            total_created += created
            total_updated += updated
            self.stdout.write(self.style.SUCCESS(f"Active processed. Created: {created}, Updated: {updated}"))
            active_resp.close()
        else:
            self.stdout.write(self.style.WARNING("No active_offer.csv to process."))

        if not skip_removed:
            self.stdout.write(f"Fetching removed: {removed_url}")
            removed_resp = self._download_csv_stream(removed_url, username, password)
            if removed_resp:
                removed = self._process_removed_stream(
                    removed_resp,
                    dry_run=dry_run,
                    progress=progress,
                    progress_every=progress_every,
                    max_rows=max_rows,
                )
                total_removed += removed
                self.stdout.write(self.style.SUCCESS(f"Removed processed. Deleted: {removed}"))
                removed_resp.close()
            else:
                self.stdout.write(self.style.WARNING("No removed_offer.csv to process."))

        summary = f"Done for {date_str}. Created: {total_created}, Updated: {total_updated}, Deleted: {total_removed}"
        if dry_run:
            summary = "[DRY-RUN] " + summary
        self.stdout.write(self.style.SUCCESS(summary))
