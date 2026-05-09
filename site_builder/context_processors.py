from django.db import connection, ProgrammingError, OperationalError

from .models import FooterColumn, ListingConfig, NavLink, Page


def site_chrome(request):
    """Expose nav links, footer columns, and nav-flagged pages to all templates.

    Defensive against:
      - The public schema (no tenant tables there).
      - Tenant schemas where migrations haven't run yet (catches ProgrammingError).
    """
    tenant = getattr(connection, "tenant", None)
    if tenant is None or not hasattr(tenant, "name"):
        return {}

    try:
        nav_links = list(
            NavLink.objects
            .filter(parent__isnull=True, is_visible=True)
            .prefetch_related("children", "page")
        )
        footer_columns = list(
            FooterColumn.objects
            .filter(is_visible=True)
            .prefetch_related("links__page")
        )
        nav_pages = list(
            Page.objects
            .filter(show_in_nav=True, is_published=True)
            .order_by("nav_order", "title")
        )
        listing_config = ListingConfig.objects.first()
    except (ProgrammingError, OperationalError):
        # Tables not yet migrated for this tenant.
        return {}

    return {
        "sb_nav_links": nav_links,
        "sb_footer_columns": footer_columns,
        "sb_nav_pages": nav_pages,
        "sb_listing_config": listing_config,
    }
