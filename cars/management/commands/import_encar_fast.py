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
from psycopg2.extras import Json, execute_values

from cars.models import (
    ApiCar,
    Manufacturer,
    CarModel,
    CarBadge,
    CarColor,
    CarSeatColor,
    BodyType,
)


class _LocalFileResponse:
    """Minimal requests.Response replacement for local-file CSV streaming.

    Lets _download_csv_stream serve a file that run_encar_import already pulled
    to local disk (via boto3 multipart, which handles R2's chunked connection
    drops far better than streaming with requests). Implements only the surface
    the stream reader uses: `.encoding`, `.iter_lines(decode_unicode)`, `.close()`,
    plus a `byte_offset` seek so the network path's retry-with-Range logic is a
    cheap no-op here.
    """

    def __init__(self, path: str, byte_offset: int = 0):
        self.encoding = "utf-8"
        self.status_code = 200
        self._f = open(path, "rb")
        if byte_offset:
            self._f.seek(byte_offset)

    def iter_lines(self, decode_unicode: bool = False):
        for raw in self._f:
            line = raw.rstrip(b"\r\n")
            yield line.decode(self.encoding, errors="replace") if decode_unicode else line

    def close(self):
        try:
            self._f.close()
        except Exception:
            pass


# ── Parallel parse workers ──────────────────────────────────────────────────
# _row_to_fields is pure CPU (CSV row dict -> field dict; no DB), so we fan it
# out across cores. On Linux the pool forks, inheriting the already-initialised
# Django state, so a worker can call the parser directly. Each worker drops the
# inherited DB connection so nobody shares the parent's psycopg2 socket; workers
# never query anyway (FK resolution + upsert stay in the main process).
_PARSE_CMD = None


def _parse_pool_init():
    global _PARSE_CMD
    try:
        from django.db import connection
        connection.close()
    except Exception:
        pass
    _PARSE_CMD = Command()


def _parse_one(row):
    return _PARSE_CMD._row_to_fields(row)


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
        # Local-file shortcut — used by run_encar_import after it has downloaded
        # the CSV to disk with boto3. Reads straight off local disk (no network,
        # no chunk-drop retries), which is the main speedup over streaming twice.
        if url.startswith("file://") or url.startswith("/"):
            local_path = url[7:] if url.startswith("file://") else url
            return _LocalFileResponse(local_path, byte_offset=byte_offset)

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
        from cars.normalization import normalize_name, normalize_body
        manufacturer_name = normalize_name(manufacturer_name)
        model_name = normalize_name(model_name)
        badge_name = normalize_name(badge_name)
        color_name = normalize_name(color_name)
        seat_color_name = normalize_name(seat_color_name)
        body_type_name = normalize_body(body_type_name)
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

        from cars.normalization import normalize_transmission, normalize_fuel
        transmission = normalize_transmission(norm.get("transmission_type") or "Unknown")
        body = norm.get("body_type")
        fuel = normalize_fuel(norm.get("engine_type"))
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

        options_choice = self._parse_json_safe(norm.get("optionsChoice") or "")
        if options_choice is not None:
            if isinstance(extra, dict):
                extra["optionsChoice"] = options_choice
            else:
                extra = {"optionsChoice": options_choice}

        # Optional new CSV column `originPrice` (만원, grade base) — added once
        # the scraper's parse.py started emitting it. Skips the per-car Encar
        # API fetch in _ensure_origin_price when present.
        raw_origin = norm.get("originPrice")
        if raw_origin not in (None, "", "null", "None"):
            if not isinstance(extra, dict):
                extra = {}
            try:
                extra["originPrice"] = int(float(raw_origin))
            except (TypeError, ValueError):
                pass

        # Real chassis VIN lives in the inspection detail (master.detail.vin);
        # fall back to the Encar listing id so the field is never empty.
        real_vin = ""
        try:
            _md = ((extra or {}).get("master") or {}).get("detail") or {}
            real_vin = (_md.get("vin") or "").strip()
        except (AttributeError, TypeError):
            real_vin = ""
        vin = real_vin or norm.get("inner_id") or norm.get("id") or ""

        # Encar model-tree fields (English) straight from the CSV. engine_group
        # falls back to a local derivation (fuel + displacement binned to 100cc)
        # so it still works on feeds that don't carry the column.
        model_version = (norm.get("model_version") or "").strip()
        model_year_range = (norm.get("model_year_range") or "").strip()
        trim_detail = (norm.get("trim_detail") or "").strip()
        engine_group = (norm.get("engine_group") or "").strip()
        if not engine_group and fuel and power:
            cc = int(round(power / 100.0)) * 100
            if cc > 0:
                engine_group = f"{fuel} {cc}cc"

        return {
            "manufacturer_name": manufacturer_name,
            "model_name": model_name,
            "badge_name": badge_name,
            "model_version": model_version[:120] or None,
            "model_year_range": model_year_range[:20] or None,
            "engine_group": engine_group[:60] or None,
            "trim_detail": trim_detail[:100] or None,
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

            now = datetime.now(timezone.utc)

            # Build one value tuple per row (FK ids resolved via the warm caches).
            # jsonb columns must be wrapped in Json(); a genuine NULL stays None.
            by_lot: Dict[str, tuple] = {}
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
                # Dedup within this batch (keep last): ON CONFLICT DO UPDATE refuses
                # to touch the same target row twice inside one INSERT.
                by_lot[ln] = (
                    ln[:20],                                                    # car_id
                    fields["title"],
                    fields["image"],
                    Json(fields["images"]) if fields["images"] is not None else None,
                    manufacturer.id,
                    fields["vin"] or ln,
                    ln,                                                         # lot_number
                    model.id,
                    fields["year"],
                    badge.id,
                    fields["model_version"],
                    fields["model_year_range"],
                    fields["engine_group"],
                    fields["trim_detail"],
                    color.id,
                    seat_color.id if seat_color else None,
                    fields["transmission"],
                    None,                                                       # engine
                    body.id if body else None,
                    fields["power"],
                    fields["price"],
                    fields["mileage"],
                    fields["drive_wheel"],
                    fields["seat_count"],
                    fields["fuel"],
                    False,                                                      # is_leasing
                    Json(fields["extra"]) if fields["extra"] is not None else None,
                    Json(fields["options"]) if fields["options"] is not None else None,
                    fields["address"],
                    False,                                                      # is_special  (Django default; DB has no default)
                    False,                                                      # is_luxury
                    False,                                                      # is_new (run_encar_import flips new rows after)
                    "available",                                                # status
                    "",                                                         # first_registration
                    "",                                                         # usage_type
                    "",                                                         # features
                    "",                                                         # inspection_notes
                    "",                                                         # inspection_report_url
                    now,                                                        # created_at (ignored on conflict)
                    now,                                                        # updated_at
                )

            values = list(by_lot.values())
            if not values:
                return

            if dry_run:
                lot_numbers = list(by_lot.keys())
                existing = set(
                    ApiCar.objects.filter(lot_number__in=lot_numbers).values_list("lot_number", flat=True)
                )
                for ln in by_lot:
                    if ln in existing:
                        updated += 1
                    else:
                        created += 1
                return

            # Single set-based upsert. RETURNING (xmax = 0) is TRUE for freshly
            # inserted rows and FALSE for rows that hit DO UPDATE — that gives the
            # created/updated split with no pre-query.
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = 0")
                    results = execute_values(
                        cursor,
                        """
                        INSERT INTO cars_apicar (
                            car_id, title, image, images, manufacturer_id, vin, lot_number,
                            model_id, year, badge_id, model_version, model_year_range,
                            engine_group, trim_detail, color_id, seat_color_id, transmission,
                            engine, body_id, power, price, mileage, drive_wheel, seat_count,
                            fuel, is_leasing, extra_features, options, address,
                            is_special, is_luxury, is_new, status, first_registration,
                            usage_type, features, inspection_notes, inspection_report_url,
                            created_at, updated_at
                        )
                        VALUES %s
                        ON CONFLICT (lot_number) DO UPDATE SET
                            car_id = EXCLUDED.car_id, title = EXCLUDED.title, image = EXCLUDED.image,
                            images = EXCLUDED.images, manufacturer_id = EXCLUDED.manufacturer_id,
                            vin = EXCLUDED.vin, model_id = EXCLUDED.model_id, year = EXCLUDED.year,
                            badge_id = EXCLUDED.badge_id, model_version = EXCLUDED.model_version,
                            model_year_range = EXCLUDED.model_year_range, engine_group = EXCLUDED.engine_group,
                            trim_detail = EXCLUDED.trim_detail, color_id = EXCLUDED.color_id,
                            seat_color_id = EXCLUDED.seat_color_id, transmission = EXCLUDED.transmission,
                            engine = EXCLUDED.engine, body_id = EXCLUDED.body_id, power = EXCLUDED.power,
                            price = EXCLUDED.price, mileage = EXCLUDED.mileage, drive_wheel = EXCLUDED.drive_wheel,
                            seat_count = EXCLUDED.seat_count, fuel = EXCLUDED.fuel, is_leasing = EXCLUDED.is_leasing,
                            extra_features = EXCLUDED.extra_features, options = EXCLUDED.options,
                            address = EXCLUDED.address, updated_at = EXCLUDED.updated_at
                        RETURNING (xmax = 0) AS inserted
                        """,
                        values,
                        page_size=1000,
                        fetch=True,
                    )
            for (inserted,) in results:
                if inserted:
                    created += 1
                else:
                    updated += 1

        row_iter = self._iter_csv_stream(resp, url=url, username=username, password=password)

        def ingest(fields) -> bool:
            """Handle one parsed row; return True to stop (max_rows reached)."""
            nonlocal processed
            processed += 1
            if fields["lot_number"]:
                seen_lot_numbers.add(fields["lot_number"])
                chunk_rows.append(fields)
                if len(chunk_rows) >= chunk_size:
                    flush_chunk(chunk_rows)
                    chunk_rows.clear()
            if progress and processed % max(1, progress_every) == 0:
                self.stdout.write(f"Processed {processed} rows... Created: {created}, Updated: {updated}")
            return bool(max_rows and processed >= max_rows)

        # The parse (_row_to_fields) is pure CPU and dominates wall-clock, so fan
        # it across cores. FK resolution + the upsert stay here in the main
        # process (inside flush_chunk). Override with ENCAR_PARSE_WORKERS;
        # default = cores - 1. Falls back to single-process if a pool can't start.
        default_workers = max(1, (os.cpu_count() or 2) - 1)
        workers = self._to_int(os.getenv("ENCAR_PARSE_WORKERS", ""), default=default_workers) or default_workers

        pool = None
        if workers > 1:
            try:
                import multiprocessing as mp
                from django.db import connections
                # Close the parent's DB connections BEFORE forking so the workers
                # don't inherit (and then tear down) the shared psycopg2 socket —
                # otherwise the main process hits "cursor already closed". Django
                # transparently reopens on the next query in flush_chunk.
                connections.close_all()
                pool = mp.get_context("fork").Pool(processes=workers, initializer=_parse_pool_init)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Parallel parse unavailable ({e}); using single process."))
                pool = None

        if pool is not None:
            self.stdout.write(f"Parsing with {workers} worker processes...")
            try:
                for fields in pool.imap(_parse_one, row_iter, chunksize=250):
                    if ingest(fields):
                        break
            finally:
                pool.terminate()
                pool.join()
        else:
            for row in row_iter:
                if ingest(self._row_to_fields(row)):
                    break

        # leftover
        if chunk_rows:
            flush_chunk(chunk_rows)

        # Generate slugs once, after all rows are upserted, for any newly-inserted
        # cars that still have none (updates keep their existing slug).
        if not dry_run:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = 0")
                    cursor.execute("""
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
