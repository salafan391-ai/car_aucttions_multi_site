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
from django.urls import path, include
from django.http import HttpResponse, HttpResponseNotFound, JsonResponse
from django.template import loader
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from tenants.views import site_settings
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
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


urlpatterns = [
    path("internal/encar-import/", trigger_encar_import, name="trigger_encar_import"),
    # ── Instant 404 for browser/bot probe paths — no DB, no template ──
    path(".well-known/<path:subpath>", lambda req, subpath: HttpResponse('', status=404, content_type='text/plain')),
    path("favicon.ico", lambda req: HttpResponse('', status=404, content_type='text/plain')),
    path("robots.txt", robots_txt),
    path("admin/", admin.site.urls),
    path("settings/", site_settings, name="site_settings"),
    path("billing/", include("billing.urls")),
    path("stripe/webhook/", stripe_webhook, name="stripe_webhook"),
    path("", include("cars.urls")),
    path("", include("site_cars.urls")),
    path("", include("site_builder.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    import debug_toolbar
    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
