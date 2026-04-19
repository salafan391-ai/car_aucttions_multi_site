from django.core.cache import cache
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Tenant


LANDING_DESIGNS = (
    'cosmos', 'minimal', 'bold', 'luxury', 'neon',
    'desert', 'split', 'dashboard', 'cockpit',
)


@receiver(post_save, sender=Tenant)
def invalidate_tenant_caches(sender, instance, **kwargs):
    schema = instance.schema_name
    cache.delete(f"tenant_branding:{schema}")
    cache.delete(f"home_html_v9:{schema}")
    cache.delete(f"home_ctx_v9:{schema}")

    try:
        from django_redis import get_redis_connection
        conn = get_redis_connection("default")
        for key in conn.keys(f"*landing_html:{schema}:*"):
            conn.delete(key)
    except Exception:
        for design in LANDING_DESIGNS:
            for sc in (0, 1):
                cache.delete(f"landing_html:{schema}:{design}:sc{sc}")
