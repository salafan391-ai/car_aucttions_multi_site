import json
from datetime import datetime

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


class Command(BaseCommand):
    help = "Import auction cars from a JSON file into ApiCar (category=auction)"

    def add_arguments(self, parser):
        parser.add_argument("json_file", type=str, help="Path to the JSON file")
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
        for fmt in ("%d/%m/%Y %I:%M %p", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(val.strip(), fmt)
            except ValueError:
                continue
        return None

    def handle(self, *args, **options):
        json_path = options["json_file"]
        dry_run = options.get("dry_run", False)

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
        badge_cache = {}
        color_cache = {}
        body_cache = {}

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
            badge_key = (model_name, car_model.id)
            if badge_key not in badge_cache:
                badge_cache[badge_key] = self._safe_get_or_create(
                    CarBadge.objects,
                    name=model_name,
                    model=car_model,
                )
            badge = badge_cache[badge_key]

            # Color
            color_name = item.get("color_en") or item.get("color") or "Unknown"
            if color_name not in color_cache:
                color_cache[color_name] = self._safe_get_or_create(
                    CarColor.objects,
                    name=color_name,
                )
            color = color_cache[color_name]

            # Body type from shape field
            shape = (item.get("shape") or "").strip()
            body_obj = None
            if shape:
                if shape not in body_cache:
                    body_cache[shape] = self._safe_get_or_create(
                        BodyType.objects,
                        name=shape,
                    )
                body_obj = body_cache[shape]

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
                "badge": badge,
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
                "body": body_obj,
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
