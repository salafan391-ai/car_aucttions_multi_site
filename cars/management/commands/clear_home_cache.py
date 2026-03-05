"""
Management command to clear the home page Redis cache for all tenants.
Use when a bad response has been cached or after view-level fixes.

Usage:
    python manage.py clear_home_cache
    heroku run python manage.py clear_home_cache --app tenant-cars
"""
from django.core.management.base import BaseCommand
from django.core.cache import cache
from django_tenants.utils import get_tenant_model


class Command(BaseCommand):
    help = "Clear home_html and home_ctx cache keys for all tenants"

    def handle(self, *args, **options):
        Tenant = get_tenant_model()
        cleared = 0
        for tenant in Tenant.objects.all():
            for prefix in ['home_html', 'home_ctx', 'car_list']:
                key = f"{prefix}:{tenant.schema_name}"
                deleted = cache.delete(key)
                if deleted:
                    self.stdout.write(f"  Cleared: {key}")
                    cleared += 1

        # Also clear with wildcard pattern if using django-redis
        try:
            from django_redis import get_redis_connection
            redis_conn = get_redis_connection("default")
            patterns = ["home_html:*", "home_ctx:*", ":1:home_html:*", ":1:home_ctx:*"]
            total_deleted = 0
            for pattern in patterns:
                keys = redis_conn.keys(pattern)
                if keys:
                    total_deleted += redis_conn.delete(*keys)
                    for k in keys:
                        self.stdout.write(f"  Redis KEYS cleared: {k.decode()}")
            if total_deleted:
                self.stdout.write(self.style.SUCCESS(
                    f"  Redis wildcard: deleted {total_deleted} additional key(s)"
                ))
        except Exception as e:
            self.stdout.write(f"  (django-redis wildcard not available: {e})")

        self.stdout.write(self.style.SUCCESS(
            f"Done. Cleared {cleared} cache key(s) via Django cache."
        ))
