import asyncio
import csv
from django.core.management.base import BaseCommand
from core.models import ApiCar,Manufacturer,CarModel,CarBadge,CarColor,CarSeatColor, BodyType, Category  # Replace with your actual model name
import test
import boto3
from botocore.client import Config
import io
import json



R2_ENDPOINT_URL = "https://5f609be3294e42fbcada608b624a1c95.r2.cloudflarestorage.com"
R2_ACCESS_KEY_ID = "b25996c10a792981965550c6f2669276"
R2_SECRET_ACCESS_KEY = "f03df43ee845395c76ffcf38ee9bf8ca33eb0bf8c5a9c07c917f498bfe45f0dd"
R2_BUCKET_NAME = "insimages"

# Initialize R2 client
s3 = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT_URL,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    config=Config(signature_version='s3v4'),
    region_name='auto'
)

# Download the file
object_name = "encar_files/encar_vehicles_detailed.json"  # Name in the bucket
local_file_path = "encar_files/encar_vehicles_detailed.json"  # Local path to save
class Command(BaseCommand):
    help = 'Import car data from JSON into the Car model'
    def handle(self, *args, **options):
        import json
        file_stream = io.BytesIO()
        s3.download_fileobj(R2_BUCKET_NAME, object_name, file_stream)
        self.stdout.write(self.style.SUCCESS(f'Downloaded {object_name} from R2 bucket {R2_BUCKET_NAME}'))
        file_stream.seek(0)
        cars = json.load(file_stream)
        self.stdout.write(self.style.SUCCESS(f'Loaded {len(cars)} cars from JSON data'))

        # Deduplicate input cars by lot_number before processing
        unique_cars = {}
        for car in cars:
            lot_number = car.get("vehicleId")
            if lot_number and lot_number not in unique_cars:
                unique_cars[lot_number] = car
        cars = list(unique_cars.values())
        self.stdout.write(self.style.SUCCESS(f'Deduplicated input: {len(cars)} unique cars to import'))

        # Extract new lot numbers from the incoming data
        new_lot_numbers = set(car.get("vehicleId") for car in cars if car.get("vehicleId"))

        from core.models import ApiCar
        # Delete cars not in the new file
        deleted_count, _ = ApiCar.objects.exclude(lot_number__in=new_lot_numbers).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} cars not present in the new file."))

        # Build caches once
        manufacturer_cache = {m.name: m for m in Manufacturer.objects.all()}
        model_cache = {}
        for m in CarModel.objects.select_related('manufacturer').all():
            model_cache[(m.name, m.manufacturer_id)] = m
        badge_cache = {}
        for b in CarBadge.objects.select_related('model').all():
            badge_cache[(b.name, b.model_id)] = b
        color_cache = {c.name: c for c in CarColor.objects.all()}
        seat_color_cache = {s.name: s for s in CarSeatColor.objects.all()}
        body_type_cache = {b.name: b for b in BodyType.objects.all()}
        category_cache = {c.name: c for c in Category.objects.all()}

        from django.db import transaction
        # Load existing lot_numbers from DB to prevent duplicates
        lot_numbers = set(ApiCar.objects.values_list('lot_number', flat=True))
        self.stdout.write(self.style.WARNING(f'Loaded {len(lot_numbers)} existing lot_numbers from database'))
        seen_input = set()
        new_cars = []
        skipped = 0
        
        for idx, car in enumerate(cars, 1):
            lot_number = str(car.get("vehicleId"))  # Convert to string to match DB storage
            # Skip if already in DB or already processed in this session
            if lot_number in lot_numbers or lot_number in seen_input:
                skipped += 1
                continue
            seen_input.add(lot_number)

            try:
                # Ensure category is a dict
                category = car.get('category', {})
                if not isinstance(category, dict):
                    category = {}
                
                # Extract manufacturer
                if category.get('type') == "TRUCK":
                    manufacturer_name = category.get('manufacturerName', 'Unknown')
                else:
                    manufacturer_name = category.get('manufacturerEnglishName', 'Unknown')
                manufacturer = manufacturer_cache.get(manufacturer_name)
                if not manufacturer:
                    manufacturer, _ = Manufacturer.objects.get_or_create(name=manufacturer_name)
                    manufacturer_cache[manufacturer_name] = manufacturer
                if category.get('type') == "TRUCK":
                    model_name = category.get('modelName', 'Unknown')
                else:
                    model_name = category.get('modelGroupEnglishName', 'Unknown')
                model_key = (model_name, manufacturer.id)
                model = model_cache.get(model_key)
                if not model:
                    model, _ = CarModel.objects.get_or_create(name=model_name, manufacturer=manufacturer)
                    model_cache[model_key] = model

                badge_name = category.get('gradeEnglishName', 'Unknown')
                badge_key = (badge_name, model.id)
                badge = badge_cache.get(badge_key)
                if not badge:
                    badge, _ = CarBadge.objects.get_or_create(name=badge_name, model=model)
                    badge_cache[badge_key] = badge

                color_name = car.get('spec', {}).get('colorName', 'Unknown')
                color = color_cache.get(color_name)
                if not color:
                    color, _ = CarColor.objects.get_or_create(name=color_name)
                    color_cache[color_name] = color

                seat_color_name = car.get('seat_color', 'Unknown')
                seat_color = seat_color_cache.get(seat_color_name)
                if not seat_color:
                    seat_color, _ = CarSeatColor.objects.get_or_create(name=seat_color_name)
                    seat_color_cache[seat_color_name] = seat_color

                body_type_name = car.get('spec', {}).get('bodyName', 'Unknown')
                body_type = body_type_cache.get(body_type_name)
                if not body_type:
                    body_type, _ = BodyType.objects.get_or_create(name=body_type_name)
                    body_type_cache[body_type_name] = body_type

                category_name = category.get('type', 'Unknown')
                category_obj = category_cache.get(category_name)
                if not category_obj:
                    category_obj, _ = Category.objects.get_or_create(name=category_name)
                    category_cache[category_name] = category_obj

                new_cars.append(ApiCar(
                    lot_number=lot_number,
                    vin=car.get('vin', ''),
                    manufacturer=manufacturer,
                    model=model,
                    badge=badge,
                    color=color,
                    seat_color=seat_color,
                    category=category_obj,
                    body=body_type,
                    year=category.get('formYear'),
                    mileage=car.get('spec', {}).get('mileage', ''),
                    transmission=car.get('spec', {}).get('transmissionName', ''),
                    price=category.get('originPrice',None) or 0,
                    fuel=car.get('spec', {}).get('fuelName', ''),
                    images=car.get('photos'),
                    options=car.get('options', {}).get('standard', []),
                    power=car.get('spec', {}).get('displacement', ''),
                    seat_count=car.get('spec', {}).get('seatCount', ''),
                    address=car.get('contact', {}).get('address',''),
                    plate_number=car.get('vehicleNo',''),
                ))
                
                # Batch insert every 500 cars using bulk_create with ignore_conflicts
                if len(new_cars) >= 500:
                    try:
                        # ignore_conflicts=True works when there's a unique constraint
                        created_objs = ApiCar.objects.bulk_create(new_cars, ignore_conflicts=True)
                        # Update lot_numbers - note: with ignore_conflicts, we get empty list back
                        # so we track all attempted lot_numbers
                        lot_numbers.update(obj.lot_number for obj in new_cars)
                        self.stdout.write(self.style.SUCCESS(f"Batch processed {len(new_cars)} cars at index {idx}"))
                    except Exception as e:
                        # Fallback to one-by-one if bulk fails
                        inserted = 0
                        for new_car in new_cars:
                            try:
                                new_car.save()
                                lot_numbers.add(new_car.lot_number)
                                inserted += 1
                            except Exception:
                                pass
                        self.stdout.write(self.style.WARNING(f"Batch insert failed, inserted {inserted}/{len(new_cars)} individually at index {idx}"))
                    new_cars = []
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error importing car at index {idx}: {e}'))
        
        # Insert remaining cars
        if new_cars:
            try:
                created_objs = ApiCar.objects.bulk_create(new_cars, ignore_conflicts=True)
                lot_numbers.update(obj.lot_number for obj in new_cars)
                self.stdout.write(self.style.SUCCESS(f"Final batch processed {len(new_cars)} cars"))
            except Exception as e:
                # Fallback to one-by-one
                inserted = 0
                for new_car in new_cars:
                    try:
                        new_car.save()
                        lot_numbers.add(new_car.lot_number)
                        inserted += 1
                    except Exception:
                        pass
                self.stdout.write(self.style.WARNING(f"Final batch insert failed, inserted {inserted}/{len(new_cars)} individually"))
        
        self.stdout.write(self.style.SUCCESS(f'Import complete: {len(cars)-skipped} new cars, {skipped} skipped (already existed)'))
