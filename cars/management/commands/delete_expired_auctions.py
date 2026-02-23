from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from django_tenants.utils import schema_context, get_public_schema_name

from tenants.models import Tenant

from cars.models import ApiCar


class Command(BaseCommand):
    help = "Delete auction cars whose auction_date has passed (runs per-tenant)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Do not delete, only report counts')
        parser.add_argument('--yes', action='store_true', help='Confirm and perform deletions without per-tenant prompt')
        parser.add_argument('--tenant', type=str, help='Schema name of a single tenant to target')
        parser.add_argument('--days', type=int, default=0, help='Only delete auctions ended more than N days ago (default: 0 = ended already)')

    def handle(self, *args, **options):
        dry_run = options.get('dry_run')
        assume_yes = options.get('yes')
        tenant_arg = options.get('tenant')
        days = options.get('days', 0) or 0

        cutoff = timezone.now() - timedelta(days=days)

        tenants = Tenant.objects.all()
        public_schema = get_public_schema_name()
        # skip public schema
        tenants = tenants.exclude(schema_name=public_schema)
        if tenant_arg:
            tenants = tenants.filter(schema_name=tenant_arg)

        total_deleted = 0
        total_found = 0

        for tenant in tenants:
            self.stdout.write(f"Processing tenant: {tenant.schema_name}")
            with schema_context(tenant.schema_name):
                # Only consider auction cars that are still marked as available —
                # we don't want to delete sold/pending records.
                # Exclude any car referenced by tenant-schema tables (SiteOrder,
                # SiteRating, SiteQuestion, SiteSoldCar) to avoid cross-schema
                # FK violations that Django's ORM cascade cannot handle.
                from site_cars.models import SiteOrder, SiteRating, SiteQuestion, SiteSoldCar
                protected_ids = set()
                protected_ids.update(SiteOrder.objects.values_list('car_id', flat=True))
                protected_ids.update(SiteRating.objects.values_list('car_id', flat=True))
                protected_ids.update(SiteQuestion.objects.exclude(car_id=None).values_list('car_id', flat=True))
                protected_ids.update(SiteSoldCar.objects.values_list('car_id', flat=True))

                qs = ApiCar.objects.filter(
                    category__name='auction', auction_date__lt=cutoff, status='available'
                ).exclude(id__in=protected_ids)
                count = qs.count()
                total_found += count
                if count == 0:
                    self.stdout.write(self.style.NOTICE(f"  No expired AVAILABLE auctions (cutoff={cutoff.isoformat()})."))
                    continue

                self.stdout.write(f"  Found {count} expired AVAILABLE auction car(s) in tenant '{tenant.schema_name}'.")

                if dry_run:
                    continue

                if not assume_yes:
                    confirm = input(f"  Delete {count} rows from tenant '{tenant.schema_name}'? [y/N]: ")
                    if confirm.lower() not in ('y', 'yes'):
                        self.stdout.write("  Skipped.")
                        continue

                # Use ORM delete inside tenant schema so cascades run correctly for tenant data
                deleted, detail = qs.delete()
                total_deleted += deleted
                self.stdout.write(self.style.SUCCESS(f"  Deleted {deleted} objects (including cascades)."))

        self.stdout.write(self.style.SUCCESS(f"Done. Found: {total_found}. Deleted: {total_deleted}. (dry_run={dry_run})"))
