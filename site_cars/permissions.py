"""Per-section dashboard permissions for tenant staff accounts.

Two tiers exist inside every tenant schema:

* **Site admin** — ``is_staff`` and ``is_superuser``. Full dashboard access, and
  the only tier that may manage staff. The SSO provisioning flow
  (``tenants/sso_views.py``) grants both flags to every tenant owner, and
  ``TenantAdmin.create_superuser_view`` does the same, so every admin that
  exists today already qualifies.
* **Limited staff** — ``is_staff`` without ``is_superuser``. Reaches exactly the
  sections ticked on their :class:`~site_cars.models.StaffAccess` row.

Both flags are schema-local: ``is_superuser`` on a tenant domain means "owner of
this site", not "platform owner". Platform-owner checks must additionally
require the public schema (see ``site_cars.views.delete_auctions``).
"""
from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.shortcuts import resolve_url
from django_tenants.utils import get_public_schema_name

# The permissionable areas of the dashboard, in display order. Anything not
# listed here (site settings, shop, page builder, billing, auction imports) is
# site-admin-only by default.
SECTIONS = (
    ("cars", "السيارات والمخزون", "إضافة وتعديل وحذف السيارات، والمزادات، والاستيراد."),
    ("sales", "الفواتير والإيصالات", "الفواتير، الإيصالات، العقود، والشحن."),
    ("orders", "طلبات العملاء", "عرض الطلبات وتحديث حالتها."),
    ("reviews", "التقييمات والأسئلة", "اعتماد التقييمات، الرد على الأسئلة، والأسئلة الشائعة."),
)

SECTION_KEYS = tuple(key for key, _label, _help in SECTIONS)

#: Section key -> the ``StaffAccess`` boolean field backing it.
SECTION_FIELDS = {key: f"can_{key}" for key in SECTION_KEYS}


def is_staff_member(user):
    """True for any dashboard account — admin or limited staff."""
    return bool(user and user.is_authenticated and user.is_staff)


def is_site_admin(user):
    """True for the owner of the current schema (full access, manages staff)."""
    return bool(is_staff_member(user) and user.is_superuser)


def allowed_sections(user):
    """The set of section keys ``user`` may reach in the current schema."""
    if not is_staff_member(user):
        return frozenset()
    if is_site_admin(user):
        return frozenset(SECTION_KEYS)
    if connection.schema_name == get_public_schema_name():
        # StaffAccess is a TENANT_APPS model — its table doesn't exist in the
        # public schema, so never query it here. Limited staff are a per-site
        # concept and have nothing to reach on the platform side anyway.
        return frozenset()
    access = getattr(user, "staff_access", None)
    if access is None:
        return frozenset()
    return frozenset(key for key in SECTION_KEYS if getattr(access, SECTION_FIELDS[key]))


def has_section(user, *sections):
    """True if ``user`` may reach *any* of ``sections``."""
    granted = allowed_sections(user)
    return any(section in granted for section in sections)


def _deny(request):
    """Send anonymous users to log in; refuse everyone else with a 403."""
    if not request.user.is_authenticated:
        return redirect_to_login(
            request.get_full_path(),
            resolve_url(settings.LOGIN_URL),
        )
    raise PermissionDenied


def staff_required(view):
    """Gate a view behind any dashboard account, admin or limited."""

    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not is_staff_member(request.user):
            return _deny(request)
        return view(request, *args, **kwargs)

    return _wrapped


def site_admin_required(view):
    """Gate a view behind the site admin — staff without superuser get a 403."""

    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not is_staff_member(request.user):
            return _deny(request)
        if not is_site_admin(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return _wrapped


def section_required(*sections):
    """Gate a view behind one or more sections; site admins always pass.

    Unknown section keys are a programming error, so fail loudly at import time
    rather than silently granting (or denying) access at request time.
    """
    unknown = set(sections) - set(SECTION_KEYS)
    if unknown:
        raise ValueError(f"Unknown dashboard section(s): {', '.join(sorted(unknown))}")

    def decorator(view):
        @wraps(view)
        def _wrapped(request, *args, **kwargs):
            if not is_staff_member(request.user):
                return _deny(request)
            if not has_section(request.user, *sections):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return _wrapped

    return decorator
