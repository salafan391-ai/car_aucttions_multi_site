"""
Management command to clear tenant-facing caches for all tenants.
Covers: tenant_branding, home_html_v9, home_ctx_v9, landing_html (all design + sc variants), car_list.

Usage:
    python manage.py clear_home_cache
    railway ssh -> /opt/venv/bin/python manage.py clear_home_cache
"""
from django.core.management.base import BaseCommand
from django.core.cache import cache
from django_tenants.utils import get_tenant_model


LANDING_DESIGNS = (
    'cosmos', 'minimal', 'bold', 'luxury', 'neon',
    'desert', 'split', 'dashboard', 'cockpit',
)


class Command(BaseCommand):
    help = "Clear tenant_branding, home_html_v9, home_ctx_v9, landing_html, and car_list caches for all tenants"

    def handle(self, *args, **options):
        Tenant = get_tenant_model()
        cleared = 0

        for tenant in Tenant.objects.all():
            schema = tenant.schema_name
            keys = [
                f"tenant_branding:{schema}",
                f"home_html_v9:{schema}",
                f"home_ctx_v9:{schema}",
                f"car_list:{schema}",
            ]
            for design in LANDING_DESIGNS:
                for sc in (0, 1):
                    keys.append(f"landing_html:{schema}:{design}:sc{sc}")

            for key in keys:
                if cache.delete(key):
                    self.stdout.write(f"  Cleared: {key}")
                    cleared += 1

        # Wildcard pass for django-redis — catches anything schema-agnostic or with prefixes we missed
        try:
            from django_redis import get_redis_connection
            redis_conn = get_redis_connection("default")
            patterns = [
                "*tenant_branding:*",
                "*home_html*",
                "*home_ctx*",
                "*landing_html:*",
                "*car_list:*",
            ]
            total_deleted = 0
            for pattern in patterns:
                rkeys = redis_conn.keys(pattern)
                if rkeys:
                    total_deleted += redis_conn.delete(*rkeys)
                    for k in rkeys:
                        self.stdout.write(f"  Redis cleared: {k.decode() if isinstance(k, bytes) else k}")
            if total_deleted:
                self.stdout.write(self.style.SUCCESS(
                    f"  Redis wildcard: deleted {total_deleted} key(s)"
                ))
        except Exception as e:
            self.stdout.write(f"  (django-redis wildcard not available: {e})")

        self.stdout.write(self.style.SUCCESS(
            f"Done. Cleared {cleared} cache key(s) via Django cache."
        ))
