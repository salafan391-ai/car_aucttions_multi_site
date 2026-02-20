from django.core.management.base import BaseCommand
from django.utils.text import slugify
from django_tenants.utils import schema_context, get_tenant_model


class Command(BaseCommand):
    help = "Backfill slugs for all ApiCar rows that are missing a slug."

    def handle(self, *args, **options):
        from cars.models import ApiCar

        TenantModel = get_tenant_model()
        for tenant in TenantModel.objects.all():
            with schema_context(tenant.schema_name):
                cars = ApiCar.objects.filter(slug__isnull=True) | ApiCar.objects.filter(slug="")
                count = 0
                for car in cars.select_related("manufacturer", "model"):
                    base = slugify(
                        f"{car.year or ''}-"
                        f"{getattr(car.manufacturer, 'name', '') or ''}-"
                        f"{getattr(car.model, 'name', '') or ''}-"
                        f"{car.pk}"
                    )
                    car.slug = base or f"car-{car.pk}"
                    car.save(update_fields=["slug"])
                    count += 1
                self.stdout.write(f"[{tenant.schema_name}] backfilled {count} slugs")

        self.stdout.write(self.style.SUCCESS("Done."))
