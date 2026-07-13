"""
Dashboard metrics helpers.

- tenant_traffic(schema): a tenant's own request volume from the Redis counters
  written by TrafficCounterMiddleware (today / week / month + a daily sparkline).
- fleet_gsc(): aggregate the cached per-tenant GSC for the owner overview.
- fleet_sales(): total orders/sold/revenue across all tenant schemas (cached,
  since it iterates schemas and the owner page auto-refreshes).
"""
import datetime


def tenant_traffic(schema, days=30):
    try:
        from django_redis import get_redis_connection
        r = get_redis_connection("default")
        today = datetime.date.today()
        counts = []
        for i in range(days - 1, -1, -1):  # oldest → today
            d = today - datetime.timedelta(days=i)
            v = r.hget(f"traf:day:{d.strftime('%Y%m%d')}", schema)
            counts.append(int(v) if v else 0)
        mx = max(counts) if counts else 0
        return {
            "today": counts[-1] if counts else 0,
            "week": sum(counts[-7:]),
            "month": sum(counts),
            "spark": [round(100 * c / mx) if mx else 0 for c in counts],
            "days": days,
        }
    except Exception:
        return None


def fleet_gsc():
    """Aggregate cached GSC (warmed by refresh_gsc) across tenant primary domains."""
    try:
        from django.core.cache import cache
        from tenants.models import Domain
        rows = []
        tot_clicks = tot_impr = 0
        for d in (Domain.objects.filter(is_primary=True)
                  .exclude(tenant__schema_name="public").select_related("tenant")):
            data = cache.get(f"gsc:v2:{d.domain}")
            if data:  # {} sentinel is falsy → skipped
                tot_clicks += data["clicks"]
                tot_impr += data["impressions"]
                rows.append({
                    "label": d.tenant.name or d.domain,
                    "domain": d.domain,
                    "clicks": data["clicks"],
                    "impressions": data["impressions"],
                })
        if not rows:
            return None
        rows.sort(key=lambda x: -x["clicks"])
        return {"total_clicks": tot_clicks, "total_impr": tot_impr, "rows": rows[:12]}
    except Exception:
        return None


def fleet_sales(cache_ttl=600):
    """Orders/sold/revenue summed across all tenant schemas. Cached (iterates schemas)."""
    from django.core.cache import cache
    key = "fleet:sales:v1"
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    data = None
    try:
        from django.db.models import Sum
        from django_tenants.utils import schema_context
        from tenants.models import Tenant
        tot_orders = tot_sold = tot_rev = 0
        per = []
        for t in Tenant.objects.exclude(schema_name="public"):
            try:
                with schema_context(t.schema_name):
                    from site_cars.models import SiteOrder, SiteSoldCar
                    o = SiteOrder.objects.count()
                    s = SiteSoldCar.objects.count()
                    rev = SiteSoldCar.objects.aggregate(x=Sum("sale_price"))["x"] or 0
            except Exception:
                continue
            tot_orders += o
            tot_sold += s
            tot_rev += rev
            if o or s:
                per.append({"label": t.name or t.schema_name, "orders": o, "sold": s, "revenue": int(rev)})
        per.sort(key=lambda x: -x["revenue"])
        data = {"orders": tot_orders, "sold": tot_sold, "revenue": int(tot_rev), "per": per[:12]}
    except Exception:
        data = None
    cache.set(key, data or {}, cache_ttl)
    return data
