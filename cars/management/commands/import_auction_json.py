import json
import os
from datetime import datetime

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.core.exceptions import MultipleObjectsReturned

from cars.models import (
    ApiCar,
    Category,
    Manufacturer,
    CarModel,
    CarBadge,
    CarColor,
    BodyType,
)

# ─── Cloudflare R2 Credentials ────────────────────────────────────────────────
R2_ACCOUNT_ID     = os.environ.get("R2_ACCOUNT_ID",         "your_cloudflare_account_id")
R2_BUCKET         = os.environ.get("R2_BUCKET",             "your-bucket-name")
R2_ACCESS_KEY_ID  = os.environ.get("R2_ACCESS_KEY_ID",      "your_r2_access_key_id")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "your_r2_secret_access_key")
# ──────────────────────────────────────────────────────────────────────────────


class Command(BaseCommand):
    help = (
        "Import auction cars from a JSON file (local path or Cloudflare R2 object key) "
        "into ApiCar (category=auction)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "json_file",
            type=str,
            help=(
                "Local path to a JSON file  OR  an R2 object key (e.g. 'auctions/2026-03-10.json'). "
                "When an R2 key is given you must also supply --r2-bucket (or set R2_BUCKET env var)."
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
        return int(val.replace(",", "").strip() or 0)

    def _parse_auction_date(self, val):
        if not val:
            return None
        from zoneinfo import ZoneInfo
        from django.utils.timezone import make_aware
        sa_tz = ZoneInfo("Asia/Riyadh")
        for fmt in ("%d/%m/%Y %I:%M %p", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                naive_dt = datetime.strptime(val.strip(), fmt)
                return make_aware(naive_dt, sa_tz)
            except ValueError:
                continue
        return None

    def _load_from_r2(self, options):
        """Download the JSON object from Cloudflare R2 and return parsed data."""
        account_id = options["r2_account_id"]
        access_key = options["r2_access_key"]
        secret_key = options["r2_secret_key"]
        bucket = options["r2_bucket"]
        key = options["json_file"]

        missing = [name for name, val in [
            ("--r2-account-id / R2_ACCOUNT_ID", account_id),
            ("--r2-access-key / R2_ACCESS_KEY_ID", access_key),
            ("--r2-secret-key / R2_SECRET_ACCESS_KEY", secret_key),
            ("--r2-bucket / R2_BUCKET", bucket),
        ] if not val]
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

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)

        # ── Load data ──────────────────────────────────────────────────────────
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

        # Get or create the "auction" category
        auction_category = self._safe_get_or_create(Category.objects, name="auction")

        # Caches for related objects
        manu_cache = {}
        model_cache = {}
        color_cache = {}

        created = 0
        updated = 0
        skipped = 0

        for i, item in enumerate(data, 1):
            car_id = (item.get("car_identifire") or item.get("car_ids") or "").strip()
            if not car_id:
                self.stdout.write(self.style.WARNING(f"  Row {i}: No car_id, skipping"))
                skipped += 1
                continue

            # Manufacturer
            make_name = item.get("make_en") or item.get("make") or "Unknown"
            if make_name not in manu_cache:
                manu_cache[make_name] = self._safe_get_or_create(
                    Manufacturer.objects,
                    defaults={"country": "Unknown"},
                    name=make_name,
                )
            manufacturer = manu_cache[make_name]

            # Model — use models_en or models field
            model_name = item.get("models_en") or item.get("models") or "Unknown"
            model_key = (model_name, manufacturer.id)
            if model_key not in model_cache:
                model_cache[model_key] = self._safe_get_or_create(
                    CarModel.objects,
                    name=model_name,
                    manufacturer=manufacturer,
                )
            car_model = model_cache[model_key]

            # Badge — auction cars don't have badge, use model name as badge
           
            # Color
            color_name = item.get("color_en") or item.get("color") or "Unknown"
            if color_name not in color_cache:
                color_cache[color_name] = self._safe_get_or_create(
                    CarColor.objects,
                    name=color_name,
                )
            color = color_cache[color_name]

           
            # Parse fields
            title = item.get("title") or f"{make_name} {model_name}"
            year = int(item.get("year") or 0)
            price = int(item.get("price") or 0)
            mileage = self._parse_mileage(item.get("mileage"))
            power = int(item.get("power") or 0)
            fuel = item.get("fuel_en") or item.get("fuel") or ""
            transmission = item.get("mission") or ""
            auction_name = item.get("auction_name") or ""
            auction_date = self._parse_auction_date(item.get("auction_date"))
            image = item.get("image") or ""
            images = item.get("images") or []
            inspection_image = item.get("inspection_image") or ""
            points = item.get("points") or item.get("score") or ""
            address = item.get("region") or ""

            if dry_run:
                action = "UPDATE" if ApiCar.objects.filter(car_id=car_id).exists() else "CREATE"
                self.stdout.write(f"  [{action}] {car_id}: {title} ({year}) - ₩{price:,}")
                if action == "CREATE":
                    created += 1
                else:
                    updated += 1
                continue

            defaults = {
                "title": title[:100],
                "image": image[:255] if image else "",
                "manufacturer": manufacturer,
                "category": auction_category,
                "auction_date": auction_date,
                "auction_name": auction_name[:100] if auction_name else "",
                "lot_number": car_id,
                "model": car_model,
                "year": year,
                "color": color,
                "transmission": transmission[:100] if transmission else "",
                "power": power,
                "price": price,
                "mileage": mileage,
                "fuel": fuel[:100] if fuel else "",
                "images": images,
                "inspection_image": inspection_image,
                "points": str(points)[:50] if points else "",
                "address": address[:255] if address else "",
                "vin": car_id,
            }

            try:
                with transaction.atomic():
                    obj, was_created = ApiCar.objects.update_or_create(
                        car_id=car_id,
                        defaults=defaults,
                    )
                    if was_created:
                        created += 1
                    else:
                        updated += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Row {i} ({car_id}): {e}"))
                skipped += 1
                continue

            if i % 50 == 0:
                self.stdout.write(f"  Processed {i}/{len(data)}...")

        prefix = "[DRY-RUN] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Done. Created: {created}, Updated: {updated}, Skipped: {skipped}"
        ))
