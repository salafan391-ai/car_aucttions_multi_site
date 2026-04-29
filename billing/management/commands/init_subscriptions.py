"""Create a Subscription row for every non-public tenant.

By default the row starts with status='none', meaning the paywall will
block the tenant until they complete checkout. Pass --grandfather to
mark all existing tenants as 'active' instead (useful before launch).
"""
from django.core.management.base import BaseCommand

from billing.models import Subscription
from tenants.models import Tenant


class Command(BaseCommand):
    help = "Create Subscription rows for all non-public tenants."

    def add_arguments(self, parser):
        parser.add_argument(
            "--grandfather",
            action="store_true",
            help="Mark all newly-created subscriptions as 'active' (no payment required).",
        )

    def handle(self, *args, **opts):
        grandfather = opts["grandfather"]
        created = 0
        for tenant in Tenant.objects.exclude(schema_name="public"):
            sub, was_created = Subscription.objects.get_or_create(tenant=tenant)
            if was_created:
                created += 1
                if grandfather:
                    sub.status = Subscription.STATUS_ACTIVE
                    sub.save(update_fields=["status", "updated_at"])
                self.stdout.write(
                    f"  + {tenant.schema_name} ({sub.status})"
                )
        self.stdout.write(self.style.SUCCESS(
            f"Done. {created} subscription row(s) created."
        ))
