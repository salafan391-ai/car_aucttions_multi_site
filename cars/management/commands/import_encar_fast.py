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
from django.db import transaction, connection

from cars.models import (
    ApiCar,
    BodyType,
    Manufacturer,
    CarModel,
    CarBadge,
    CarColor,
    CarSeatColor,
)


class Command(BaseCommand):
    help = "Fast import of Encar daily exports using chunked upsert and batched deletes"

    # ------------- CLI -------------
    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            help="Date in YYYY-MM-DD for the export folder (UTC). Defaults to today's UTC date.",
        )
        parser.add_argument(
            "--host",
            type=str,
            default=(
                os.getenv("ENCAR_HOST")
                or os.getenv("ENCAR_AUTObASE_HOST")
            ),
            help="Base host for autobase (env: ENCAR_HOST; fallback: ENCAR_AUTObASE_HOST)",
        )
        parser.add_argument(
            "--username",
            type=str,
            default=(
                os.getenv("ENCAR_USER")
                or os.getenv("ENCAR_AUTObASE_USER")
            ),
            help="Basic auth username (env: ENCAR_USER; fallback: ENCAR_AUTObASE_USER)",
        )
        parser.add_argument(
            "--password",
            type=str,
            default=(
                os.getenv("ENCAR_PASS")
                or os.getenv("ENCAR_AUTObASE_PASS")
            ),
            help="Basic auth password (env: ENCAR_PASS; fallback: ENCAR_AUTObASE_PASS)",
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
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=500,
            help="Number of rows per processing chunk for active feed (default 500)",
        )
        parser.add_argument(
            "--update-batch-size",
            type=int,
            default=100,
            help="Batch size for bulk_update and bulk_create (default 100)",
        )
        parser.add_argument(
            "--delete-batch-size",
            type=int,
            default=1000,
            help="Batch size for removed deletions (default 1000)",
        )

    # ------------- helpers -------------
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

    def _get_or_create_related(self, caches: Dict[str, Dict], manufacturer_name: str, model_name: str, badge_name: str, color_name: str, seat_color_name: Optional[str], body_type_name: Optional[str] = None):
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

        # Body Type (optional)
        body_cache = caches.setdefault("body_type", {})
        body_obj = None
        if body_type_name:
            if body_type_name not in body_cache:
                body_cache[body_type_name] = self._safe_get_or_create(
                    BodyType.objects,
                    name=body_type_name,
                )
            body_obj = body_cache[body_type_name]

        return manufacturer, model, badge, color, seat_color_obj, body_obj

    def _row_to_fields(self, row: Dict[str, str]) -> Dict[str, Any]:
        norm = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}

        manufacturer_name = norm.get("mark") or "Unknown"
        model_name = norm.get("model") or "Unknown"
        badge_name = norm.get("configuration") or norm.get("complectation") or model_name

        lot_number = norm.get("inner_id") or norm.get("id") or ""

        year = self._to_int(norm.get("year"), default=0, max_value=2147483647)
        mileage = self._to_int(norm.get("km_age"), default=0, max_value=9223372036854775807)
        price = self._to_int(norm.get("price"), default=0, max_value=9223372036854775807)
        power = self._to_int(norm.get("displacement") or norm.get("dispacement"), default=0, max_value=2147483647)
        price_kw = price * 10000

        transmission = norm.get("transmission_type") or "Unknown"
        body_type = norm.get("body_type")
        fuel = norm.get("engine_type")
        color_name = norm.get("color") or "Unknown"
        seat_color_name = norm.get("seatColor")
        drive_wheel = norm.get("prep_drive_type") or ""
        seat_count = norm.get("seatCount") or ""
        address = norm.get("address") or ""

        raw_images = norm.get("images") or ""
        parsed_images = self._parse_json_safe(raw_images)
        images_list = None
        if isinstance(parsed_images, list):
            images_list = [str(x) for x in parsed_images if x]
        elif isinstance(parsed_images, str):
            if parsed_images:
                images_list = [x.strip() for x in parsed_images.split(",") if x.strip()]
        image = self._first_image(raw_images)

        title = f"{manufacturer_name} {model_name} {badge_name} {year}".strip()

        options = self._parse_json_safe(norm.get("options") or "")
        extra = self._parse_json_safe(norm.get("extra") or "")

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
            "address": address,
        }

    # ------------- processing -------------
    def _iter_csv_stream(self, resp: requests.Response) -> Iterable[Dict[str, str]]:
        raw_iter = resp.iter_lines(decode_unicode=False)
        line_iter = (
            (line.decode(resp.encoding or "utf-8", errors="replace") if isinstance(line, (bytes, bytearray)) else line)
            for line in raw_iter if line is not None
        )
        # Increase CSV field size limit to handle very large fields (e.g., long image lists or JSON)
        try:
            csv.field_size_limit(1024 * 1024 * 1024)  # 1GB
        except OverflowError:
            csv.field_size_limit(sys.maxsize)
        reader = csv.DictReader(line_iter, delimiter='|')
        for row in reader:
            yield row

    def _process_active_chunked(self, resp: requests.Response, *, chunk_size: int, batch_size: int, progress: bool = False, progress_every: int = 5000, max_rows: int = 0, dry_run: bool = False) -> Tuple[int, int]:
        created = 0
        updated = 0
        processed = 0

        caches: Dict[str, Dict] = {}
        cache_reset_every = 50000  # rows after which we reset related caches to limit memory
        chunk_rows: List[Dict[str, Any]] = []

        def flush_chunk(rows: List[Dict[str, Any]]):
            nonlocal created, updated
            if not rows:
                return

            lot_numbers = [r["lot_number"] for r in rows if r["lot_number"]]
            if not lot_numbers:
                return

            # Build a map of existing cars by lot_number -> id. Since lot_number is not unique,
            # pick the first one by id to keep deterministic behavior. Use values() to avoid
            # loading full model instances into memory.
            existing_map: Dict[str, int] = {}
            for row in (
                ApiCar.objects
                .filter(lot_number__in=lot_numbers)
                .order_by('id')
                .values('id', 'lot_number')
            ):
                ln = row['lot_number']
                if ln not in existing_map:
                    existing_map[ln] = row['id']

            new_objs: List[ApiCar] = []
            upd_objs: List[ApiCar] = []

            for fields in rows:
                ln = fields["lot_number"]
                manufacturer, model, badge, color, seat_color, body = self._get_or_create_related(
                    caches,
                    fields["manufacturer_name"],
                    fields["model_name"],
                    fields["badge_name"],
                    fields["color_name"],
                    fields["seat_color_name"],
                    fields["body_type"],
                )
                if ln in existing_map:
                    existing_id = existing_map[ln]
                    updated += 1
                    if not dry_run:
                        upd_objs.append(ApiCar(
                            id=existing_id,
                            car_id=ln,
                            title=fields["title"],
                            image=fields["image"],
                            images=fields["images"],
                            manufacturer=manufacturer,
                            vin=fields["vin"] or ln,
                            lot_number=ln,
                            model=model,
                            year=fields["year"],
                            badge=badge,
                            color=color,
                            seat_color=seat_color,
                            transmission=fields["transmission"],
                            engine=None,
                            body=body,
                            power=fields["power"],
                            price=fields["price"],
                            mileage=fields["mileage"],
                            drive_wheel=fields["drive_wheel"],
                            seat_count=fields["seat_count"],
                            fuel=fields["fuel"],
                            is_leasing=False,
                            extra_features=fields["extra"],
                            options=fields["options"],
                            address=fields["address"],
                        ))
                else:
                    created += 1
                    if not dry_run:
                        new_objs.append(ApiCar(
                            car_id=ln,
                            title=fields["title"],
                            image=fields["image"],
                            images=fields["images"],
                            manufacturer=manufacturer,
                            vin=fields["vin"] or ln,
                            lot_number=ln,
                            model=model,
                            year=fields["year"],
                            badge=badge,
                            color=color,
                            seat_color=seat_color,
                            transmission=fields["transmission"],
                            engine=None,
                            body=body,
                            power=fields["power"],
                            price=fields["price"],
                            mileage=fields["mileage"],
                            drive_wheel=fields["drive_wheel"],
                            seat_count=fields["seat_count"],
                            fuel=fields["fuel"],
                            is_leasing=False,
                            extra_features=fields["extra"],
                            options=fields["options"],
                            address=fields["address"],
                        ))

            if dry_run:
                return

            with transaction.atomic():
                # Disable statement timeout for this transaction so Heroku's
                # default timeout (30s) doesn't cancel large bulk operations.
                connection.cursor().execute("SET LOCAL statement_timeout = 0")
                if new_objs:
                    ApiCar.objects.bulk_create(new_objs, ignore_conflicts=True, batch_size=batch_size)
                if upd_objs:
                    ApiCar.objects.bulk_update(
                        upd_objs,
                        fields=[
                            'car_id','title','image','images','manufacturer','vin','lot_number','model','year','badge','color','seat_color','transmission','engine','body','power','price','mileage','drive_wheel','seat_count','fuel','is_leasing','extra_features','options','address'
                        ],
                        batch_size=batch_size,
                    )

        for row in self._iter_csv_stream(resp):
            processed += 1
            fields = self._row_to_fields(row)
            if not fields["lot_number"]:
                continue
            chunk_rows.append(fields)

            if len(chunk_rows) >= chunk_size:
                flush_chunk(chunk_rows)
                chunk_rows.clear()

            if progress and processed % max(1, progress_every) == 0:
                self.stdout.write(f"Processed {processed} rows... Created: {created}, Updated: {updated}")

            if max_rows and processed >= max_rows:
                break

        # leftover
        if chunk_rows:
            flush_chunk(chunk_rows)

        return created, updated

    def _process_removed_chunked(self, resp: requests.Response, *, delete_batch_size: int, progress: bool = False, progress_every: int = 5000, max_rows: int = 0, dry_run: bool = False) -> int:
        removed = 0
        processed = 0
        batch: List[str] = []
        reader = self._iter_csv_stream(resp)

        def flush_delete(b: List[str]):
            nonlocal removed
            if not b:
                return
            if dry_run:
                # Estimate would be unknown without hitting DB; skip counting exact rows here
                return
            with transaction.atomic():
                connection.cursor().execute("SET LOCAL statement_timeout = 0")
                qs = ApiCar.objects.filter(lot_number__in=b)
                cnt = qs.count()
                if cnt:
                    qs.delete()
                removed += cnt

        for row in reader:
            processed += 1
            lot_number = (row.get("inner_id") or row.get("id") or "").strip()
            if not lot_number:
                continue
            batch.append(lot_number)

            if len(batch) >= delete_batch_size:
                flush_delete(batch)
                batch.clear()

            if progress and processed % max(1, progress_every) == 0:
                self.stdout.write(f"Processed {processed} removed rows... Deleted so far: {removed}")

            if max_rows and processed >= max_rows:
                break

        if batch:
            flush_delete(batch)

        return removed

    # ------------- handle -------------
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
        chunk_size = options.get("chunk_size", 500)
        batch_size = options.get("update_batch_size", 100)
        delete_batch_size = options.get("delete_batch_size", 1000)

        # Validate required connection settings early to avoid AttributeError
        missing = []
        if not host:
            missing.append("--host or ENCAR_HOST/ENCAR_AUTObASE_HOST")
        if not username:
            missing.append("--username or ENCAR_USER/ENCAR_AUTObASE_USER")
        if not password:
            missing.append("--password or ENCAR_PASS/ENCAR_AUTObASE_PASS")
        if missing:
            raise CommandError(
                "Missing required parameters: "
                + ", ".join(missing)
                + "\nExample: python manage.py import_encar_fast --host https://autobase-berger.auto-parser.ru --username admin --password <pass> --date "
                + date_str
            )

        active_url, removed_url = self._build_urls(host, date_str)
        self.stdout.write(f"Fetching active: {active_url}")
        active_resp = self._download_csv_stream(active_url, username, password)

        total_created = total_updated = total_removed = 0

        if active_resp:
            created, updated = self._process_active_chunked(
                active_resp,
                chunk_size=chunk_size,
                batch_size=batch_size,
                progress=progress,
                progress_every=progress_every,
                max_rows=max_rows,
                dry_run=dry_run,
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
                removed = self._process_removed_chunked(
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

        summary = f"Done for {date_str}. Created: {total_created}, Updated: {total_updated}, Deleted: {total_removed}"
        if dry_run:
            summary = "[DRY-RUN] " + summary
        self.stdout.write(self.style.SUCCESS(summary))
