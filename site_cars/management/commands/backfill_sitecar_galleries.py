from django.core.management.base import BaseCommand
from django.db.models import Count
from django_tenants.utils import get_tenant_model, schema_context

from cars.models import ApiCar
from site_cars.models import SiteCar, SiteCarImage

PREFIX = "apicar_"


def _img_url(item):
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return (item.get("url") or item.get("image") or "").strip()
    return ""


def _image_urls(api_car):
    urls = []
    if isinstance(api_car.images, list):
        for item in api_car.images:
            url = _img_url(item)
            if url and len(url) <= 500 and url not in urls:
                urls.append(url)
    if not urls and api_car.image:
        urls = [api_car.image]
    return urls


class Command(BaseCommand):
    help = (
        "Backfill photo galleries for cars saved from the public catalogue back "
        "when the copy only carried the cover image. Only touches saved cars "
        "whose gallery is empty, so manually added photos are never disturbed."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="report what would change without writing")
        parser.add_argument("--schema", help="limit to a single tenant schema")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        tenants = get_tenant_model().objects.exclude(schema_name="public")
        if opts.get("schema"):
            tenants = tenants.filter(schema_name=opts["schema"])

        total_cars = total_imgs = skipped = 0
        for tenant in tenants:
            try:
                with schema_context(tenant.schema_name):
                    qs = (SiteCar.objects.filter(external_id__startswith=PREFIX)
                          .annotate(gcount=Count("gallery")).filter(gcount=0))
                    cars = imgs = 0
                    for car in qs:
                        api_car = self._source(car.external_id[len(PREFIX):])
                        if api_car is None:
                            skipped += 1
                            continue
                        urls = _image_urls(api_car)
                        if not urls:
                            skipped += 1
                            continue
                        if not dry:
                            SiteCarImage.objects.bulk_create(
                                [SiteCarImage(car=car, image_url=u, order=i)
                                 for i, u in enumerate(urls)],
                                batch_size=100,
                            )
                            if not car.external_image_url:
                                car.external_image_url = urls[0]
                                car.save(update_fields=["external_image_url"])
                        cars += 1
                        imgs += len(urls)
                    if cars:
                        self.stdout.write(
                            f"  {tenant.schema_name}: {cars} cars, {imgs} photos")
                    total_cars += cars
                    total_imgs += imgs
            except Exception as exc:
                self.stderr.write(f"  {tenant.schema_name}: ERROR {exc}")

        verb = "would backfill" if dry else "backfilled"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {total_cars} cars / {total_imgs} photos"
            + (f" ({skipped} skipped - source car missing or no photos)" if skipped else "")))

    def _source(self, car_id):
        """The catalogue row a saved car was copied from (car_id may be int or str)."""
        car = ApiCar.objects.filter(car_id=car_id).first()
        if car is None and str(car_id).isdigit():
            car = ApiCar.objects.filter(car_id=int(car_id)).first()
        return car
