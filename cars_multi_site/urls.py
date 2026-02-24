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

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse
from tenants.views import site_settings


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
    path("robots.txt", robots_txt),
    path("admin/", admin.site.urls),
    path("settings/", site_settings, name="site_settings"),
    path("", include("cars.urls")),
    path("", include("site_cars.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
