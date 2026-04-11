import csv
import ast
import io
import itertools
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import MultipleObjectsReturned
from django.db import transaction, connection

from cars.models import (
    ApiCar,
    Manufacturer,
    CarModel,
    CarBadge,
    CarColor,
    CarSeatColor,
    BodyType,
)


class Command(BaseCommand):
    help = "Fast import of Encar daily exports using chunked upsert and batched deletes"

    # ------------- CLI -------------
    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            type=str,
            default=None,
            help=(
                "Direct URL to a public active_offer CSV (e.g. R2/S3 presigned URL). "
                "When set, --host/--date/--username/--password are ignored and "
                "--skip-removed is implied (no removed_offer.csv)."
            ),
        )
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
            default=2000,
            help="Number of rows per processing chunk for active feed (default 2000)",
        )
        parser.add_argument(
            "--update-batch-size",
            type=int,
            default=1000,
            help="Batch size for bulk_update and bulk_create (default 1000)",
        )
        parser.add_argument(
            "--delete-batch-size",
            type=int,
            default=3000,
            help="Batch size for removed deletions (default 3000)",
        )
        parser.add_argument(
            "--delete-stale",
            action="store_true",
            help="After importing the active CSV, delete any DB car whose lot_number was not in the CSV.",
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

    def _download_csv_stream(self, url: str, username: str = "", password: str = "", byte_offset: int = 0) -> Optional[requests.Response]:
        headers = {}
        if byte_offset > 0:
            headers["Range"] = f"bytes={byte_offset}-"
        try:
            auth = (username, password) if username and password else None
            resp = requests.get(url, auth=auth, timeout=60, stream=True, headers=headers)
            if resp.status_code == 404:
                self.stdout.write(self.style.WARNING(f"CSV not found: {url}"))
                resp.close()
                return None
            # 206 = Partial Content (range accepted), 200 = full response
            if resp.status_code not in (200, 206):
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

    _ENCAR_IMAGE_BASE = "https://ci.encar.com"
    _ENCAR_IMAGE_PARAMS = "?impolicy=heightRate&rh=653&cw=1160&ch=653&cg=Center"

    def _parse_json_safe(self, s: str):
        if not s:
            return None
        s = s.strip()
        # Try standard JSON first
        try:
            return json.loads(s)
        except Exception:
            pass
        # Fallback: Python literal (single-quoted dicts/lists from new CSV format)
        try:
            return ast.literal_eval(s)
        except Exception:
            pass
        if "," in s:
            return [x.strip() for x in s.split(",") if x.strip()]
        return s

    def _image_path_to_url(self, path: str) -> str:
        """Convert a relative Encar image path to a full CDN URL."""
        path = path.lstrip("/")
        return f"{self._ENCAR_IMAGE_BASE}/{path}{self._ENCAR_IMAGE_PARAMS}"

    def _extract_images(self, images_field: str) -> tuple:
        """
        Parse the images field and return (first_image_url, all_image_urls_list).

        New format: list of dicts  {'code': '001', 'path': '/carpicture08/...', 'type': 'OUTER'}
          - types: OUTER (exterior), INNER (interior), OPTION (options), THUMBNAIL (skip — duplicates)
          - sorted: OUTER → INNER → OPTION, then by numeric code within each group
        Old format: list of plain URL strings — kept as-is.
        """
        if not images_field:
            return None, None
        parsed = self._parse_json_safe(images_field)
        if not isinstance(parsed, list) or not parsed:
            if isinstance(parsed, str):
                return parsed, [parsed]
            return None, None

        _TYPE_ORDER = {"OUTER": 0, "INNER": 1, "OPTION": 2}

        structured = []
        plain_urls = []

        for item in parsed:
            if isinstance(item, dict):
                img_type = item.get("type", "")
                if img_type == "THUMBNAIL":
                    continue  # skip — duplicates of real images
                path = item.get("path", "")
                if not path:
                    continue
                try:
                    code_num = int(item.get("code", "999"))
                except (ValueError, TypeError):
                    code_num = 999
                sort_key = (_TYPE_ORDER.get(img_type, 3), code_num)
                url = self._image_path_to_url(path)
                structured.append((sort_key, url))
            elif isinstance(item, str) and item:
                plain_urls.append(item)

        if structured:
            structured.sort(key=lambda x: x[0])
            urls = [u for _, u in structured]
            return urls[0], urls

        if plain_urls:
            return plain_urls[0], plain_urls

        return None, None

    def _first_image(self, images_field: str) -> Optional[str]:
        first, _ = self._extract_images(images_field)
        return first

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
        norm = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k is not None}

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
        body = norm.get("body_type")
        fuel = norm.get("engine_type")
        color_name = norm.get("color") or "Unknown"
        seat_color_name = norm.get("seatColor")
        drive_wheel = norm.get("prep_drive_type") or ""
        seat_count = norm.get("seatCount") or ""
        address = norm.get("address") or ""

        raw_images = norm.get("images") or ""
        image, images_list = self._extract_images(raw_images)

        title = f"{manufacturer_name} {model_name} {badge_name} {year}".strip()

        options = self._parse_json_safe(norm.get("options") or "")
        extra = self._parse_json_safe(norm.get("extra") or "")
        record = self._parse_json_safe(norm.get("record") or "")
        if record is not None:
            if isinstance(extra, dict):
                extra["record"] = record
            else:
                extra = {"record": record}

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
            "body": body,
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
    def _iter_csv_stream(self, resp: requests.Response, url: str = "", username: str = "", password: str = "", delimiter: str = "") -> Iterable[Dict[str, str]]:
        """Stream-parse a CSV (auto-detects delimiter if not given), transparently reconnecting on network drops."""
        MAX_RETRIES = 5
        RETRY_WAIT  = 5  # seconds between reconnect attempts

        try:
            csv.field_size_limit(1024 * 1024 * 1024)
        except OverflowError:
            csv.field_size_limit(sys.maxsize)

        encoding  = resp.encoding or "utf-8"
        bytes_read = 0
        header_line: Optional[str] = None
        detected_delimiter: Optional[str] = delimiter or None
        retries = 0

        current_resp = resp

        while True:
            try:
                raw_iter = current_resp.iter_lines(decode_unicode=False)

                def decoded_lines(raw):
                    nonlocal bytes_read
                    for raw_line in raw:
                        if raw_line is None:
                            continue
                        if isinstance(raw_line, (bytes, bytearray)):
                            bytes_read += len(raw_line) + 1  # +1 for the newline stripped by iter_lines
                            yield raw_line.decode(encoding, errors="replace")
                        else:
                            bytes_read += len(raw_line.encode(encoding, errors="replace")) + 1
                            yield raw_line

                line_iter = decoded_lines(raw_iter)

                if header_line is None:
                    # First time — auto-detect delimiter from first line if not given
                    first_line = next(line_iter, "")
                    first_line = first_line.lstrip('\ufeff')  # strip UTF-8 BOM if present
                    if not detected_delimiter:
                        detected_delimiter = ',' if first_line.count(',') >= first_line.count('|') else '|'
                    header_line = first_line
                    reader = csv.DictReader(
                        itertools.chain([first_line], line_iter),
                        delimiter=detected_delimiter,
                    )
                    for row in reader:
                        yield row
                else:
                    # After reconnect — server resumes from byte_offset (no header in stream).
                    # Prepend the saved header line so DictReader can parse field names.
                    reader = csv.DictReader(
                        itertools.chain([header_line], line_iter),
                        delimiter=detected_delimiter,
                    )
                    for row in reader:
                        yield row

                # Clean exit — stream finished
                break

            except (
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as exc:
                current_resp.close()

                if not url or retries >= MAX_RETRIES:
                    raise

                retries += 1
                self.stdout.write(self.style.WARNING(
                    f"Stream dropped at ~{bytes_read // 1024 // 1024} MB "
                    f"(attempt {retries}/{MAX_RETRIES}): {exc}. Reconnecting in {RETRY_WAIT}s…"
                ))
                time.sleep(RETRY_WAIT)

                new_resp = self._download_csv_stream(url, username, password, byte_offset=bytes_read)
                if new_resp is None:
                    raise RuntimeError(f"Could not reconnect to {url} after drop at byte {bytes_read}")
                current_resp = new_resp

    def _process_active_chunked(self, resp: requests.Response, *, url: str = "", username: str = "", password: str = "", chunk_size: int, batch_size: int, progress: bool = False, progress_every: int = 5000, max_rows: int = 0, dry_run: bool = False) -> Tuple[int, int, set]:
        created = 0
        updated = 0
        processed = 0
        seen_lot_numbers: set = set()

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

            # Build a map of existing cars by lot_number -> {id}.
            existing_map: Dict[str, dict] = {}
            for row in (
                ApiCar.objects
                .filter(lot_number__in=lot_numbers)
                .order_by('id')
                .values('id', 'lot_number')
            ):
                ln = row['lot_number']
                if ln not in existing_map:
                    existing_map[ln] = row

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
                    fields["body"],
                )
                if ln in existing_map:
                    updated += 1
                    if not dry_run:
                        upd_objs.append(ApiCar(
                            id=existing_map[ln]["id"],
                            car_id=ln[:20],
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
                            car_id=ln[:20],
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

            update_fields = [
                'car_id','title','image','images','manufacturer','vin','lot_number','model','year','badge',
                'color','seat_color','transmission','engine','body','power','price','mileage',
                'drive_wheel','seat_count','fuel','is_leasing','extra_features','options','address'
            ]

            # bulk_update existing cars
            if upd_objs:
                for i in range(0, len(upd_objs), batch_size):
                    sub_batch = upd_objs[i : i + batch_size]
                    with transaction.atomic():
                        connection.cursor().execute("SET LOCAL statement_timeout = 0")
                        ApiCar.objects.bulk_update(sub_batch, fields=update_fields, batch_size=len(sub_batch))

            # bulk_create new cars
            if new_objs:
                with transaction.atomic():
                    connection.cursor().execute("SET LOCAL statement_timeout = 0")
                    ApiCar.objects.bulk_create(new_objs, ignore_conflicts=True, batch_size=batch_size)
                    # Generate slugs for newly created cars that have none
                    connection.cursor().execute("""
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
                    """)

        for row in self._iter_csv_stream(resp, url=url, username=username, password=password):
            processed += 1
            fields = self._row_to_fields(row)
            if not fields["lot_number"]:
                continue
            seen_lot_numbers.add(fields["lot_number"])
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

        return created, updated, seen_lot_numbers

    def _process_removed_chunked(self, resp: requests.Response, *, url: str = "", username: str = "", password: str = "", delete_batch_size: int, progress: bool = False, progress_every: int = 5000, max_rows: int = 0, dry_run: bool = False) -> int:
        removed = 0
        processed = 0
        batch: List[str] = []
        reader = self._iter_csv_stream(resp, url=url, username=username, password=password)

        from django_tenants.utils import get_tenant_model
        tenant_schemas = list(
            get_tenant_model().objects
            .exclude(schema_name="public")
            .values_list("schema_name", flat=True)
        )

        def flush_delete(b: List[str]):
            nonlocal removed
            if not b:
                return
            if dry_run:
                return
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM cars_wishlist WHERE car_id IN (SELECT id FROM cars_apicar WHERE lot_number = ANY(%s))",
                        [b],
                    )
                    cursor.execute(
                        "DELETE FROM cars_carimage WHERE car_id IN (SELECT id FROM cars_apicar WHERE lot_number = ANY(%s))",
                        [b],
                    )
                    for schema in tenant_schemas:
                        for table in ("site_cars_siterating", "site_cars_sitequestion", "site_cars_siteorder", "site_cars_sitesoldcar"):
                            cursor.execute(
                                f'DELETE FROM "{schema}".{table} WHERE car_id IN (SELECT id FROM cars_apicar WHERE lot_number = ANY(%s))',
                                [b],
                            )
                    cursor.execute(
                        "DELETE FROM cars_apicar WHERE lot_number = ANY(%s) RETURNING id",
                        [b],
                    )
                    removed += cursor.rowcount

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

        self.stdout.write(
            f"Removed summary — CSV rows: {processed}, "
            f"matched & deleted from DB: {removed}, "
            f"not in DB (already gone): {processed - removed}"
        )
        return removed

    # ------------- handle -------------
    def handle(self, *args, **options):
        date_str = options.get("date") or self._utc_today()
        direct_url = options.get("url")
        host = options.get("host")
        username = options.get("username") or ""
        password = options.get("password") or ""
        skip_removed = options.get("skip_removed", False)
        dry_run = options.get("dry_run", False)
        progress = options.get("progress", False)
        progress_every = options.get("progress_every", 5000)
        max_rows = options.get("max_rows", 0)
        chunk_size = options.get("chunk_size", 2000)
        batch_size = options.get("update_batch_size", 1000)
        delete_batch_size = options.get("delete_batch_size", 3000)
        delete_stale = options.get("delete_stale", False)

        def _delete_stale_cars(seen: set, dry_run: bool) -> int:
            """Delete any ApiCar whose lot_number was not in the active CSV.

            Uses a temporary table to avoid passing 100k+ values in a NOT IN
            clause, which causes statement timeouts on Heroku Postgres.
            """
            if not seen:
                self.stdout.write(self.style.WARNING("Skipping stale deletion — no lot numbers were collected."))
                return 0
            self.stdout.write(f"Deleting stale cars (not in CSV)... {len(seen):,} lot numbers seen in CSV.")

            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = 0")

                    # Load all seen lot_numbers into a temp table for fast NOT EXISTS join
                    cursor.execute("""
                        CREATE TEMP TABLE _seen_lots (lot_number TEXT PRIMARY KEY)
                        ON COMMIT DROP
                    """)
                    seen_list = list(seen)
                    for i in range(0, len(seen_list), 10000):
                        batch = seen_list[i:i + 10000]
                        args = ",".join(cursor.mogrify("(%s)", [v]).decode() for v in batch)
                        cursor.execute(f"INSERT INTO _seen_lots (lot_number) VALUES {args} ON CONFLICT DO NOTHING")

                    # Only target Encar-imported cars (category IS NULL).
                    # Auction cars and other categorised cars are managed separately.
                    stale_filter = (
                        "category_id IS NULL "
                        "AND lot_number NOT IN (SELECT lot_number FROM _seen_lots)"
                    )

                    if dry_run:
                        cursor.execute(f"SELECT COUNT(*) FROM cars_apicar WHERE {stale_filter}")
                        count = cursor.fetchone()[0]
                        self.stdout.write(f"[DRY-RUN] Would delete {count} stale Encar cars (auction/categorised cars are excluded).")
                        return count

                    cursor.execute(f"SELECT COUNT(*) FROM cars_apicar WHERE {stale_filter}")
                    total_stale = cursor.fetchone()[0]
                    self.stdout.write(f"Found {total_stale:,} stale cars to delete.")

                    if total_stale:
                        from django_tenants.utils import get_tenant_model
                        tenant_schemas = list(
                            get_tenant_model().objects
                            .exclude(schema_name="public")
                            .values_list("schema_name", flat=True)
                        )
                        cursor.execute(f"DELETE FROM cars_wishlist WHERE car_id IN (SELECT id FROM cars_apicar WHERE {stale_filter})")
                        cursor.execute(f"DELETE FROM cars_carimage WHERE car_id IN (SELECT id FROM cars_apicar WHERE {stale_filter})")
                        for schema in tenant_schemas:
                            for table in ("site_cars_siterating", "site_cars_sitequestion", "site_cars_siteorder", "site_cars_sitesoldcar"):
                                cursor.execute(f'DELETE FROM "{schema}".{table} WHERE car_id IN (SELECT id FROM cars_apicar WHERE {stale_filter})')
                        cursor.execute(f"DELETE FROM cars_apicar WHERE {stale_filter}")
                        deleted = cursor.rowcount
                    else:
                        deleted = 0

            self.stdout.write(self.style.SUCCESS(f"Stale deletion done. Deleted: {deleted}"))
            return deleted

        # ── Direct URL mode ──────────────────────────────────────────────────
        if direct_url:
            self.stdout.write(f"Fetching active (direct URL): {direct_url}")
            active_resp = self._download_csv_stream(direct_url)
            if active_resp:
                created, updated, seen = self._process_active_chunked(
                    active_resp,
                    url=direct_url,
                    chunk_size=chunk_size,
                    batch_size=batch_size,
                    progress=progress,
                    progress_every=progress_every,
                    max_rows=max_rows,
                    dry_run=dry_run,
                )
                active_resp.close()
                stale_deleted = _delete_stale_cars(seen, dry_run) if delete_stale else 0
                summary = f"Done (direct URL). Created: {created}, Updated: {updated}, Stale deleted: {stale_deleted}"
                if dry_run:
                    summary = "[DRY-RUN] " + summary
                self.stdout.write(self.style.SUCCESS(summary))
            else:
                self.stdout.write(self.style.ERROR(f"Could not download: {direct_url}"))
            return

        # ── Autobase mode (original flow) ────────────────────────────────────
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
                + "\nTip: pass a public CSV with --url <https://...csv> to skip auth entirely."
            )

        active_url, removed_url = self._build_urls(host, date_str)
        self.stdout.write(f"Fetching active: {active_url}")
        active_resp = self._download_csv_stream(active_url, username, password)

        total_created = total_updated = total_removed = 0
        seen_all: set = set()

        if active_resp:
            created, updated, seen_all = self._process_active_chunked(
                active_resp,
                url=active_url,
                username=username,
                password=password,
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

        if delete_stale and seen_all:
            total_removed += _delete_stale_cars(seen_all, dry_run)
        elif not skip_removed:
            self.stdout.write(f"Fetching removed: {removed_url}")
            removed_resp = self._download_csv_stream(removed_url, username, password)
            if removed_resp:
                removed = self._process_removed_chunked(
                    removed_resp,
                    url=removed_url,
                    username=username,
                    password=password,
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
