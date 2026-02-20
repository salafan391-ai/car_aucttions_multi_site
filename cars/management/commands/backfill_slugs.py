from django.core.management.base import BaseCommand
from django.utils.text import slugify
from django_tenants.utils import schema_context, get_tenant_model

BATCH_SIZE = 500


class Command(BaseCommand):
    help = "Backfill slugs for all ApiCar rows that are missing a slug (batched)."

    def handle(self, *args, **options):
        from cars.models import ApiCar

        TenantModel = get_tenant_model()
        for tenant in TenantModel.objects.all():
            with schema_context(tenant.schema_name):
                total = 0
                while True:
                    # Fetch one batch of IDs at a time to avoid timeout
                    batch = list(
                        ApiCar.objects
                        .filter(slug__isnull=True)
                        .select_related("manufacturer", "model")
                        .values("pk", "year",
                                "manufacturer__name", "model__name")[:BATCH_SIZE]
                    )
                    if not batch:
                        # Also clear empty-string slugs
                        batch = list(
                            ApiCar.objects
                            .filter(slug="")
                            .select_related("manufacturer", "model")
                            .values("pk", "year",
                                    "manufacturer__name", "model__name")[:BATCH_SIZE]
                        )
                    if not batch:
                        break

                    for row in batch:
                        base = slugify(
                            f"{row['year'] or ''}-"
                            f"{row['manufacturer__name'] or ''}-"
                            f"{row['model__name'] or ''}-"
                            f"{row['pk']}"
                        )
                        slug = base or f"car-{row['pk']}"
                        ApiCar.objects.filter(pk=row["pk"]).update(slug=slug)

                    total += len(batch)
                    self.stdout.write(
                        f"[{tenant.schema_name}] {total} slugs done..."
                    )

                self.stdout.write(
                    self.style.SUCCESS(f"[{tenant.schema_name}] backfilled {total} slugs total")
                )

        self.stdout.write(self.style.SUCCESS("Done."))
