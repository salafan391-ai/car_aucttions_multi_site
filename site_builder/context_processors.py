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

    # Only show the "my orders" nav link once a car is actually linked to the
    # user — an order they placed or an invoice linked to their account.
    user_has_orders = False
    u = getattr(request, "user", None)
    if u is not None and getattr(u, "is_authenticated", False):
        try:
            from site_cars.models import SiteOrder, SiteBill
            user_has_orders = (
                SiteOrder.objects.filter(user=u).exists()
                or SiteBill.objects.filter(buyer_user=u).exists()
            )
        except (ProgrammingError, OperationalError):
            user_has_orders = False

    try:
        from site_cars.models import SiteFaq
        has_faqs = SiteFaq.objects.filter(is_published=True).exists()
    except (ProgrammingError, OperationalError):
        has_faqs = False

    return {
        "sb_nav_links": nav_links,
        "sb_footer_columns": footer_columns,
        "sb_nav_pages": nav_pages,
        "sb_listing_config": listing_config,
        "user_has_orders": user_has_orders,
        "has_faqs": has_faqs,
    }
