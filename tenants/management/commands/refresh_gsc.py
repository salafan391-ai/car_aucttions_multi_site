"""
Warm the Google Search Console analytics cache for every tenant's primary
domain, so the tenant dashboards read instantly. Run nightly (added to
cron_import.sh, after the cache clear).
"""
from django.core.management.base import BaseCommand

from tenants.models import Domain
from tenants.gsc import get_search_metrics


class Command(BaseCommand):
    help = "Refresh the GSC search-analytics cache for every tenant's primary domain."

    def handle(self, *args, **options):
        qs = (Domain.objects
              .filter(is_primary=True)
              .exclude(tenant__schema_name="public")
              .select_related("tenant"))
        seen = ok = 0
        for d in qs:
            seen += 1
            try:
                data = get_search_metrics(d.domain, force=True)
            except Exception as e:
                self.stdout.write(f"  {d.domain}: error {e}")
                continue
            if data:
                ok += 1
                self.stdout.write(f"  {d.domain}: {data['clicks']} clicks / {data['impressions']} impr")
            else:
                self.stdout.write(f"  {d.domain}: no GSC data")
        self.stdout.write(self.style.SUCCESS(f"warmed GSC cache for {ok}/{seen} tenant domains"))
