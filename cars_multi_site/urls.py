"""
URL configuration for cars_multi_site project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

import os

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include, re_path
from django.http import HttpResponse, HttpResponseNotFound, JsonResponse
from django.template import loader
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from tenants.views import site_settings, set_dashboard_password
from tenants.sso_views import launch as sso_launch, enter as sso_enter
from cars.vps_health import vps_health
from tenants import oauth_relay
from tenants.telegram_views import telegram_webhook
from billing.views import stripe_webhook


handler404 = 'cars_multi_site.urls.custom_404'


@csrf_exempt
@require_POST
def trigger_encar_import(request):
    import urllib.request
    import urllib.error

    secret = os.environ.get("WEBHOOK_SECRET", "")
    if not secret or request.headers.get("X-Webhook-Secret") != secret:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    api_token = os.environ.get("RAILWAY_API_TOKEN", "")
    service_id = os.environ.get("RAILWAY_CRON_SERVICE_ID", "")
    if not api_token or not service_id:
        return JsonResponse({"error": "Railway config missing"}, status=500)

    import json as _json

    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json", "User-Agent": "encar-webhook/1.0"}

    # Get latest deployment ID for the cron service
    payload = _json.dumps({"query": f'{{ deployments(input: {{ serviceId: "{service_id}" }}) {{ edges {{ node {{ id status }} }} }} }}'})
    req = urllib.request.Request("https://backboard.railway.app/graphql/v2", data=payload.encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = _json.loads(resp.read())
    deployment_id = next(
        e["node"]["id"] for e in data["data"]["deployments"]["edges"]
        if e["node"]["status"] in ("SUCCESS", "CRASHED")
    )

    # Trigger redeploy
    payload = _json.dumps({"query": f'mutation {{ deploymentRedeploy(id: "{deployment_id}") {{ id status }} }}'})
    req = urllib.request.Request("https://backboard.railway.app/graphql/v2", data=payload.encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = _json.loads(resp.read())

    new_deployment = result["data"]["deploymentRedeploy"]
    return JsonResponse({"status": "triggered", "deployment_id": new_deployment["id"]})


def custom_404(request, exception=None):
    # Short-circuit well-known bot/browser probes — no template, no DB queries.
    path = request.path_info
    if path.startswith('/.well-known/') or path in ('/favicon.ico', '/apple-touch-icon.png'):
        return HttpResponse('', status=404, content_type='text/plain')
    template = loader.get_template('404.html')
    return HttpResponseNotFound(template.render(request=request))


def robots_txt(request):
    lines = [
        # ── Block aggressive AI / SEO bots entirely ──
        "User-agent: GPTBot",
        "Disallow: /",
        "",
        "User-agent: ChatGPT-User",
        "Disallow: /",
        "",
        "User-agent: Google-Extended",
        "Disallow: /",
        "",
        "User-agent: CCBot",
        "Disallow: /",
        "",
        "User-agent: DotBot",
        "Disallow: /",
        "",
        "User-agent: AhrefsBot",
        "Disallow: /",
        "",
        "User-agent: SemrushBot",
        "Disallow: /",
        "",
        "User-agent: MJ12bot",
        "Disallow: /",
        "",
        # ── Normal bots: allow detail pages, block filtered/paginated lists ──
        "User-agent: *",
        "Disallow: /order/",
        "Disallow: /my-orders/",
        "Disallow: /login/",
        "Disallow: /register/",
        "Disallow: /admin/",
        "Disallow: /site/",
        "Disallow: /inbox/",
        "Disallow: /cars/?*page=",
        "Disallow: /cars/?*car_type=",
        "Disallow: /cars/?*sort=",
        "Disallow: /expired-auctions/",
        "Allow: /cars/",
        "Allow: /",
        "",
        "Crawl-delay: 5",
        "",
        f"Sitemap: {request.scheme}://{request.get_host()}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def gsc_verify_file(request, fname):
    """Serve Google's site-verification FILE (e.g. /google<hash>.html) from a
    never-cached endpoint, so verification never depends on the home-page cache.
    Returns the file only when it matches the current tenant's stored token."""
    from django.db import connection as _c
    from tenants.models import Tenant
    schema = getattr(_c, "schema_name", "public")
    token = (Tenant.objects.filter(schema_name=schema)
             .values_list("gsc_verification_token", flat=True).first() or "")
    if token and fname == token:
        resp = HttpResponse(f"google-site-verification: {token}", content_type="text/html")
        resp["Cache-Control"] = "no-store, max-age=0"
        return resp
    return HttpResponse(status=404)


def sitemap_xml(request):
    """Per-tenant XML sitemap — built from the request host so each domain lists
    its own catalog (shared Encar/auction cars it shows + its own SiteCars)."""
    from django.core.cache import cache
    from django.urls import reverse
    from django.template.loader import render_to_string
    from django.db import connection as _conn
    from cars.models import ApiCar

    schema = getattr(_conn, "schema_name", "public")
    host = request.get_host()
    from cars.views import _tenant_catalog_sig
    cache_key = f"sitemap_xml:{schema}:{host}:{_tenant_catalog_sig(getattr(_conn, 'tenant', None))}"
    xml = cache.get(cache_key)
    if xml is None:
        base = f"{request.scheme}://{host}"
        urls = []
        for name, freq, pri in [("home", "daily", "1.0"), ("car_list", "daily", "0.9"),
                                 ("site_car_list", "daily", "0.7"), ("faq", "monthly", "0.5")]:
            try:
                urls.append({"loc": base + reverse(name), "lastmod": None, "changefreq": freq, "priority": pri})
            except Exception:
                pass

        tenant = getattr(_conn, "tenant", None)
        api_qs = ApiCar.objects.exclude(slug__isnull=True).exclude(slug="")
        # Expired auctions now 404 on their detail page — keep them out of the sitemap.
        from django.utils import timezone as _tz
        api_qs = api_qs.exclude(category__name="auction", auction_date__lt=_tz.now())
        # Only list reachable cars: encar (NULL category) + auctions + any market
        # this tenant has enabled. Non-enabled market cars 404, so keep them out.
        from django.db.models import Q as _Q
        from cars.views import _apply_tenant_catalog, _tenant_market_names
        _mkt = list(_tenant_market_names(tenant))
        _reach = _Q(category__isnull=True) | _Q(category__name="auction")
        if _mkt:
            _reach |= _Q(category__name__in=_mkt)
        api_qs = api_qs.filter(_reach)
        # Respect the tenant's visibility toggles + catalog filter.
        api_qs = _apply_tenant_catalog(api_qs, tenant)
        for slug, upd in api_qs.order_by("-updated_at").values_list("slug", "updated_at")[:30000]:
            urls.append({"loc": f"{base}/cars/{slug}/", "lastmod": upd, "changefreq": "weekly", "priority": "0.7"})

        if tenant is not None and schema != "public" and getattr(tenant, "show_site_cars", True):
            try:
                from site_cars.models import SiteCar, exclude_expired_damaged
                # Ended damaged auctions 404 too — keep them out of the sitemap.
                _sc_qs = exclude_expired_damaged(SiteCar.objects.exclude(status="sold"))
                for pk, upd in (_sc_qs.order_by("-updated_at")
                                .values_list("pk", "updated_at")[:10000]):
                    urls.append({"loc": f"{base}/our-cars/{pk}/", "lastmod": upd, "changefreq": "weekly", "priority": "0.6"})
            except Exception:
                pass

        xml = render_to_string("sitemap.xml", {"urls": urls})
        cache.set(cache_key, xml, 60 * 60 * 3)  # 3h
    return HttpResponse(xml, content_type="application/xml; charset=utf-8")


urlpatterns = [
    path("internal/encar-import/", trigger_encar_import, name="trigger_encar_import"),
    # ── Instant 404 for browser/bot probe paths — no DB, no template ──
    path(".well-known/<path:subpath>", lambda req, subpath: HttpResponse('', status=404, content_type='text/plain')),
    path("favicon.ico", lambda req: HttpResponse('', status=404, content_type='text/plain')),
    path("robots.txt", robots_txt),
    path("sitemap.xml", sitemap_xml),
    re_path(r"^(?P<fname>google[\w-]+\.html)$", gsc_verify_file),
    path("vps-health/", vps_health, name="vps_health"),
    path("admin/", admin.site.urls),
    path("settings/", site_settings, name="site_settings"),
    path("settings/password/", set_dashboard_password, name="set_dashboard_password"),
    # SSO bridge from the pdf_export project — provisions a tenant for the
    # signed-in user and bounces them to their subdomain.
    path("sso/launch/", sso_launch, name="sso_launch"),
    path("sso/enter/", sso_enter, name="sso_enter"),
    path("billing/", include("billing.urls")),
    path("stripe/webhook/", stripe_webhook, name="stripe_webhook"),
    path("accounts/", include("allauth.urls")),
    # Single-callback Google OAuth relay (works across all tenant domains).
    path("oauth/google/start/", oauth_relay.google_start, name="google_oauth_start"),
    path("oauth/google/relay/", oauth_relay.google_relay, name="google_oauth_relay"),
    path("oauth/google/resume/", oauth_relay.google_resume, name="google_oauth_resume"),
    # Telegram bot webhook (fixed URL; secret in the path).
    path("telegram/webhook/<str:secret>/", telegram_webhook, name="telegram_webhook"),
    path("", include("assistant.urls")),
    path("", include("cars.urls")),
    path("", include("site_cars.urls")),
    path("", include("site_shop.urls")),
    path("", include("site_builder.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    import debug_toolbar
    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
