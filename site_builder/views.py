from django.db import OperationalError, ProgrammingError
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from site_cars.models import SiteCar

from .models import Page, PageSection


def _attach_section_data(sections):
    """For featured_cars / brand_strip sections, attach the queryset they need.

    Each section's `config` JSON drives the query. Examples:
      featured_cars: {"limit": 8, "manufacturer": "bmw", "is_featured": true, "status": "available"}
      brand_strip:   {"manufacturers": ["bmw", "mercedes-benz", "kia"]}
    """
    for s in sections:
        cfg = s.config or {}
        if s.type == PageSection.TYPE_FEATURED_CARS:
            qs = SiteCar.objects.all()
            if cfg.get("status"):
                qs = qs.filter(status=cfg["status"])
            else:
                qs = qs.filter(status="available")
            if cfg.get("is_featured"):
                qs = qs.filter(is_featured=True)
            for field in ("manufacturer", "model", "fuel", "transmission", "body_type"):
                value = cfg.get(field)
                if value:
                    qs = qs.filter(**{f"{field}__iexact": value})
            limit = int(cfg.get("limit", 8))
            s.cars = list(qs.order_by("-is_featured", "-created_at")[:limit])
        elif s.type == PageSection.TYPE_BRAND_STRIP:
            manufacturers = cfg.get("manufacturers") or []
            s.brand_items = [{"name": m} for m in manufacturers if m]
    return sections


@require_GET
def page_view(request, slug):
    try:
        page = Page.objects.get(slug=slug, is_published=True)
    except Page.DoesNotExist:
        raise Http404("Page not found")

    sections = list(page.sections.filter(is_visible=True).order_by("order", "id"))
    _attach_section_data(sections)

    return render(
        request,
        "site_builder/page.html",
        {"page": page, "sections": sections},
    )


@require_GET
def home_view(request):
    """Render the Page with kind='home' if one exists; otherwise 404 so the
    project's existing home view at the same URL can take precedence in URL order."""
    response = render_home_if_configured(request)
    if response is None:
        raise Http404("No site_builder home page configured")
    return response


def render_home_if_configured(request):
    """If a published Page(kind='home') exists for the current tenant, render it
    and return the response. Otherwise return None so callers can fall through.

    Defensive against missing tables (public schema, fresh tenant pre-migration)."""
    try:
        page = Page.objects.get(kind=Page.KIND_HOME, is_published=True)
    except (Page.DoesNotExist, ProgrammingError, OperationalError):
        return None
    sections = list(page.sections.filter(is_visible=True).order_by("order", "id"))
    _attach_section_data(sections)
    return render(
        request,
        "site_builder/page.html",
        {"page": page, "sections": sections},
    )
