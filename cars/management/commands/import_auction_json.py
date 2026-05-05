import json
import os
from datetime import datetime

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from django.core.exceptions import MultipleObjectsReturned
from django.core.management.base import BaseCommand, CommandError
from django.db import connection as _conn, transaction

from cars.models import (
    ApiCar,
    Category,
    Manufacturer,
    CarModel,
    CarBadge,
    CarColor,
)

# ─── Cloudflare R2 Credentials ────────────────────────────────────────────────
R2_ACCOUNT_ID        = os.environ.get("R2_ACCOUNT_ID",         "your_cloudflare_account_id")
R2_BUCKET            = os.environ.get("R2_BUCKET",             "your-bucket-name")
R2_ACCESS_KEY_ID     = os.environ.get("R2_ACCESS_KEY_ID",      "your_r2_access_key_id")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "your_r2_secret_access_key")
# ──────────────────────────────────────────────────────────────────────────────


class Command(BaseCommand):
    """
    Import auction cars from a JSON feed (local file or Cloudflare R2 object key)
    into ApiCar (category=auction).

    Behavior is intentionally identical to the dashboard "Upload auction JSON"
    view (site_cars.views.upload_auction_json):

      * pre-fetches FK lookup tables (manufacturers, models, badges, colors)
      * batch-translates Arabic option names via Google Translate (cached)
      * resolves badges by reusing existing rows when the feed omits one
      * bulk-creates new ApiCar rows; bulk-updates existing ones (matched by car_id)
      * backfills empty slugs via raw SQL after the import
    """

    help = (
        "Import auction cars from a JSON file (local path or Cloudflare R2 "
        "object key) into ApiCar (category=auction). Mirrors the dashboard "
        "upload-auction-json view."
    )

    # ──────────────────────────── Argparse ────────────────────────────

    def add_arguments(self, parser):
        parser.add_argument(
            "json_file",
            type=str,
            help=(
                "Local path to a JSON file  OR  an R2 object key (e.g. "
                "'auctions/2026-03-10.json'). When an R2 key is given you must "
                "also supply --r2-bucket (or set R2_BUCKET env var)."
            ),
        )
        parser.add_argument(
            "--r2",
            action="store_true",
            help="Fetch the JSON from Cloudflare R2 instead of the local filesystem.",
        )
        parser.add_argument(
            "--r2-bucket",
            type=str,
            default=os.environ.get("R2_BUCKET", R2_BUCKET),
            help="R2 bucket name (or set R2_BUCKET env var).",
        )
        parser.add_argument(
            "--r2-account-id",
            type=str,
            default=os.environ.get("R2_ACCOUNT_ID", R2_ACCOUNT_ID),
            help="Cloudflare Account ID (or set R2_ACCOUNT_ID env var).",
        )
        parser.add_argument(
            "--r2-access-key",
            type=str,
            default=os.environ.get("R2_ACCESS_KEY_ID", R2_ACCESS_KEY_ID),
            help="R2 Access Key ID (or set R2_ACCESS_KEY_ID env var).",
        )
        parser.add_argument(
            "--r2-secret-key",
            type=str,
            default=os.environ.get("R2_SECRET_ACCESS_KEY", R2_SECRET_ACCESS_KEY),
            help="R2 Secret Access Key (or set R2_SECRET_ACCESS_KEY env var).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would happen without writing to DB",
        )

    # ──────────────────────────── Parsing helpers ────────────────────────────
    # Same helpers used by site_cars.views.upload_auction_json — kept here so
    # the two paths handle the feed identically.

    def _safe_get_or_create(self, manager, defaults=None, **kwargs):
        try:
            obj, _ = manager.get_or_create(defaults=defaults or {}, **kwargs)
            return obj
        except MultipleObjectsReturned:
            return manager.filter(**kwargs).order_by("id").first()

    def _parse_mileage(self, val):
        if not val:
            return 0
        if isinstance(val, (int, float)):
            return int(val)
        cleaned = (
            str(val)
            .replace(",", "")
            .replace("km", "")
            .replace("KM", "")
            .replace("Km", "")
            .strip()
        )
        try:
            return int(cleaned) if cleaned else 0
        except ValueError:
            return 0

    def _parse_power(self, val):
        if not val:
            return 0
        if isinstance(val, (int, float)):
            return int(val)
        cleaned = str(val).replace(",", "").replace("cc", "").replace("CC", "").strip()
        try:
            return int(cleaned) if cleaned else 0
        except ValueError:
            return 0

    def _parse_auction_date(self, val):
        if not val:
            return None
        from zoneinfo import ZoneInfo
        from django.utils.timezone import make_aware
        sa_tz = ZoneInfo("Asia/Riyadh")
        for fmt in (
            "%d/%m/%Y %I:%M %p",
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                naive_dt = datetime.strptime(val.strip(), fmt)
                return make_aware(naive_dt, sa_tz)
            except ValueError:
                continue
        return None

    # ──────────────────────────── R2 fetch ────────────────────────────

    def _load_from_r2(self, options):
        account_id = options["r2_account_id"]
        access_key = options["r2_access_key"]
        secret_key = options["r2_secret_key"]
        bucket = options["r2_bucket"]
        key = options["json_file"]

        missing = [
            name for name, val in [
                ("--r2-account-id / R2_ACCOUNT_ID", account_id),
                ("--r2-access-key / R2_ACCESS_KEY_ID", access_key),
                ("--r2-secret-key / R2_SECRET_ACCESS_KEY", secret_key),
                ("--r2-bucket / R2_BUCKET", bucket),
            ] if not val
        ]
        if missing:
            raise CommandError(
                "Missing R2 credentials / config:\n  " + "\n  ".join(missing)
            )

        endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        self.stdout.write(f"Fetching s3://{bucket}/{key} from R2 …")

        try:
            s3 = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name="auto",
            )
            response = s3.get_object(Bucket=bucket, Key=key)
            raw = response["Body"].read()
        except ClientError as e:
            raise CommandError(f"R2 ClientError: {e}")
        except BotoCoreError as e:
            raise CommandError(f"R2 BotoCoreError: {e}")

        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise CommandError(f"Invalid JSON from R2: {e}")

    # ──────────────────────────── Main ────────────────────────────

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)

        # Load the JSON.
        if options["r2"]:
            data = self._load_from_r2(options)
        else:
            json_path = options["json_file"]
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except FileNotFoundError:
                raise CommandError(f"File not found: {json_path}")
            except json.JSONDecodeError as e:
                raise CommandError(f"Invalid JSON: {e}")

        if not isinstance(data, list):
            raise CommandError("JSON must be a list of car objects")

        self.stdout.write(f"Found {len(data)} cars in JSON file")

        # Local imports — match the dashboard view layout.
        from cars.normalization import normalize_transmission, normalize_fuel
        from cars.translation_utils import translate_batch

        auction_category = self._safe_get_or_create(Category.objects, name="auction")

        # Batch-translate every unique Arabic option name once.
        unique_option_ar: set[str] = set()
        for item in data:
            for name in item.get("option") or []:
                if isinstance(name, str) and name.strip():
                    unique_option_ar.add(name.strip())
        option_translations = translate_batch(
            unique_option_ar, ["en", "ru", "es"], source="ar"
        )

        # Existing car_ids already in the DB (decides create vs. update).
        incoming_ids = [
            (item.get("car_identifire") or item.get("car_ids") or "").strip()
            for item in data
        ]
        existing_car_ids = set(
            ApiCar.objects.filter(car_id__in=incoming_ids).values_list(
                "car_id", flat=True
            )
        )

        # Pre-load every related lookup row.
        all_manufacturers = {m.name: m for m in Manufacturer.objects.all()}
        all_models = {
            (m.name, m.manufacturer_id): m
            for m in CarModel.objects.select_related("manufacturer").all()
        }
        all_colors = {c.name: c for c in CarColor.objects.all()}
        all_badges = {
            (b.name, b.model_id): b
            for b in CarBadge.objects.select_related("model").all()
        }

        new_manufacturers = {}
        new_models = {}
        new_colors = {}

        cars_to_create = []
        cars_to_update = []
        seen_car_ids = set()
        created = updated = skipped = 0

        # Pass 1: collect missing FK rows so we can bulk-create them.
        for item in data:
            car_id = (item.get("car_identifire") or item.get("car_ids") or "").strip()
            if not car_id:
                skipped += 1
                continue

            make_name = item.get("make_en") or item.get("make") or "Unknown"
            if make_name not in all_manufacturers and make_name not in new_manufacturers:
                new_manufacturers[make_name] = Manufacturer(
                    name=make_name, country="Unknown"
                )

            model_name = item.get("models_en") or item.get("models") or "Unknown"
            # We don't know the manufacturer.id for newly-created makes yet, so
            # key the staging dict by model name and resolve after bulk-create.
            if model_name not in new_models and (model_name, None) not in all_models:
                new_models[model_name] = (model_name, make_name)

            color_name = item.get("color_en") or item.get("color") or "Unknown"
            if color_name not in all_colors and color_name not in new_colors:
                new_colors[color_name] = CarColor(name=color_name)

        # Dry-run short-circuits before any writes (FK rows included).
        if dry_run:
            for item in data:
                car_id = (
                    item.get("car_identifire") or item.get("car_ids") or ""
                ).strip()
                if not car_id:
                    continue
                action = "UPDATE" if car_id in existing_car_ids else "CREATE"
                if action == "CREATE":
                    if car_id in seen_car_ids:
                        skipped += 1
                        continue
                    seen_car_ids.add(car_id)
                    created += 1
                else:
                    updated += 1
                self.stdout.write(
                    f"  [{action}] {car_id}: "
                    f"{item.get('title') or item.get('make_en') or ''}"
                )
            self.stdout.write(self.style.SUCCESS(
                f"[DRY-RUN] Done. Created: {created}, Updated: {updated}, "
                f"Skipped: {skipped}"
            ))
            return

        # Bulk-create missing manufacturers.
        if new_manufacturers:
            Manufacturer.objects.bulk_create(
                new_manufacturers.values(), ignore_conflicts=True
            )
            all_manufacturers.update({
                m.name: m
                for m in Manufacturer.objects.filter(
                    name__in=new_manufacturers.keys()
                )
            })

        if new_colors:
            CarColor.objects.bulk_create(new_colors.values(), ignore_conflicts=True)
            all_colors.update({
                c.name: c
                for c in CarColor.objects.filter(name__in=new_colors.keys())
            })

        if new_models:
            models_to_create = []
            for model_name, make_name in new_models.values():
                manufacturer_obj = all_manufacturers.get(make_name)
                if manufacturer_obj:
                    models_to_create.append(
                        CarModel(name=model_name, manufacturer=manufacturer_obj)
                    )
            if models_to_create:
                CarModel.objects.bulk_create(
                    models_to_create, ignore_conflicts=True
                )
            all_models.update({
                (m.name, m.manufacturer_id): m
                for m in CarModel.objects.filter(
                    name__in=[name for name, _ in new_models.values()]
                ).select_related("manufacturer")
            })

        # Pass 2: build car payloads.
        for i, item in enumerate(data, 1):
            car_id = (item.get("car_identifire") or item.get("car_ids") or "").strip()
            if not car_id:
                continue

            make_name = item.get("make_en") or item.get("make") or "Unknown"
            manufacturer = all_manufacturers.get(make_name)

            model_name = item.get("models_en") or item.get("models") or "Unknown"
            model_key = (model_name, manufacturer.id if manufacturer else None)
            car_model = all_models.get(model_key)
            if not car_model and manufacturer:
                unknown_key = ("Unknown", manufacturer.id)
                car_model = all_models.get(unknown_key)
                if not car_model:
                    car_model = CarModel.objects.create(
                        name="Unknown", manufacturer=manufacturer
                    )
                    all_models[(car_model.name, car_model.manufacturer_id)] = car_model

            # Badge: prefer feed's; otherwise reuse an existing one for the
            # model, falling back to a single 'Unknown' placeholder per model.
            raw_badge = (
                item.get("badge_en") or item.get("badge") or item.get("trim")
            )
            badge = None
            if raw_badge and raw_badge.strip():
                badge_name = raw_badge.strip()
                badge_key = (badge_name, car_model.id if car_model else None)
                badge = all_badges.get(badge_key)
                if not badge and car_model:
                    badge = CarBadge.objects.filter(
                        model=car_model, name__iexact=badge_name
                    ).first()
                    if not badge:
                        badge = CarBadge.objects.create(
                            name=badge_name, model=car_model
                        )
                    all_badges[(badge.name, badge.model_id)] = badge
            elif car_model:
                badge = CarBadge.objects.filter(model=car_model).first()
                if not badge:
                    badge = CarBadge.objects.create(name="Unknown", model=car_model)
                all_badges[(badge.name, badge.model_id)] = badge

            if not badge:
                skipped += 1
                continue

            color_name = item.get("color_en") or item.get("color") or "Unknown"
            color = all_colors.get(color_name)

            title = item.get("title") or f"{make_name} {model_name}"

            # Autohub feeds carry a parallel `option` (Arabic names) alongside
            # `options` (objects with image URLs). Zip them so each stored
            # option carries its Arabic label plus translations.
            raw_options = item.get("options") or []
            raw_option_ar = item.get("option") or []
            enriched_options = []
            for idx, opt in enumerate(raw_options):
                if isinstance(opt, dict):
                    opt_copy = dict(opt)
                    if idx < len(raw_option_ar):
                        ar_name = (raw_option_ar[idx] or "").strip()
                        opt_copy["name_ar"] = ar_name
                        tr = option_translations.get(ar_name, {})
                        opt_copy["name_en"] = tr.get("en", ar_name)
                        opt_copy["name_ru"] = tr.get("ru", ar_name)
                        opt_copy["name_es"] = tr.get("es", ar_name)
                    enriched_options.append(opt_copy)

            car_data = {
                "car_id": car_id,
                "title": title[:100],
                "image": (item.get("image") or "")[:255],
                "manufacturer": manufacturer,
                "category": auction_category,
                "auction_date": self._parse_auction_date(item.get("auction_date")),
                "auction_name": (item.get("auction_name") or "")[:100],
                "lot_number": car_id,
                "model": car_model,
                "badge": badge,
                "year": int(item.get("year") or 0),
                "color": color,
                "transmission": (
                    normalize_transmission(
                        item.get("mission_en") or item.get("mission") or ""
                    )
                    or ""
                )[:100],
                "power": self._parse_power(item.get("power")),
                "price": int(item.get("price") or 0),
                "mileage": self._parse_mileage(item.get("mileage")),
                "fuel": (
                    normalize_fuel(item.get("fuel_en") or item.get("fuel") or "")
                    or ""
                )[:100],
                "images": item.get("images") or [],
                "inspection_image": item.get("inspection_image") or "",
                "points": str(item.get("points") or item.get("score") or "")[:50],
                "address": (item.get("region") or "")[:255],
                "seat_count": int(item.get("seats") or 0),
                "entry": item.get("entry") or "",
                "vin": car_id,
                "drive_wheel": (item.get("wheel") or "")[:100],
                "options": enriched_options,
            }

            if car_id in existing_car_ids:
                cars_to_update.append(car_data)
            elif car_id in seen_car_ids:
                # Duplicate within the uploaded file — skip to avoid bulk_create IntegrityError
                skipped += 1
                continue
            else:
                seen_car_ids.add(car_id)
                cars_to_create.append(ApiCar(**car_data))

            if i % 200 == 0:
                self.stdout.write(f"  Prepared {i}/{len(data)}…")

        # Pass 3: write.
        with transaction.atomic():
            if cars_to_create:
                ApiCar.objects.bulk_create(
                    cars_to_create, batch_size=500, ignore_conflicts=True
                )
                created = len(cars_to_create)

            if cars_to_update:
                existing_cars = {
                    car.car_id: car
                    for car in ApiCar.objects.filter(
                        car_id__in=[c["car_id"] for c in cars_to_update]
                    )
                }
                cars_to_bulk_update = []
                for car_data in cars_to_update:
                    cid = car_data.pop("car_id")
                    if cid in existing_cars:
                        car = existing_cars[cid]
                        for key, value in car_data.items():
                            setattr(car, key, value)
                        cars_to_bulk_update.append(car)
                if cars_to_bulk_update:
                    ApiCar.objects.bulk_update(
                        cars_to_bulk_update,
                        [
                            "title", "image", "manufacturer", "category",
                            "auction_date", "auction_name", "lot_number", "model",
                            "year", "color", "transmission", "power", "price",
                            "mileage", "fuel", "images", "inspection_image",
                            "points", "address", "vin", "seat_count", "entry",
                            "drive_wheel", "options",
                        ],
                        batch_size=500,
                    )
                    updated = len(cars_to_bulk_update)

            # Backfill any empty slugs (covers both newly-bulk_created rows
            # whose save() was bypassed and any pre-existing blanks).
            with _conn.cursor() as cur:
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

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created: {created}, Updated: {updated}, Skipped: {skipped}"
        ))
