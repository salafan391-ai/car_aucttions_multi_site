"""SSO bridge from the pdf_export project into the site-builder.

pdf_export signs a payload containing the user's email + business name with
a shared secret, then sends the browser here with `?token=…`. This view
verifies the signature (5-minute max age), provisions a Tenant + Domain
for the user if they don't already have one, and bounces them to their
subdomain.

Security model:
- HMAC via Django's TimestampSigner with `SSO_SHARED_SECRET` (same value
  set on both projects).
- Token is single-use-by-virtue-of-being-time-bound: 5-minute window.
- No tokens are stored — replay protection is the timestamp + secret only.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import urllib.request

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.hashers import make_password
from django.core.files.base import ContentFile
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db import connection
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django_tenants.utils import schema_context

from tenants.models import Tenant, Domain


log = logging.getLogger(__name__)
User = get_user_model()


SSO_MAX_AGE = 5 * 60   # seconds
SSO_SALT    = "tenant-cars-sso"   # MUST match pdf_export's signer salt


def _bad(request, msg: str, status: int = 400):
    return render(request, "tenants/sso_error.html", {"message": msg}, status=status)


def _slugify_owner(payload: dict) -> str:
    """Derive a URL-safe schema/subdomain slug from the SSO payload.

    Preference order:
      1. username  (pdf_export usernames are usually URL-friendly already)
      2. email local-part
      3. random 8-char fallback
    Lowercased, non-[a-z0-9] collapsed to '-', length capped at 30.
    """
    candidates = [
        (payload.get("username") or "").strip(),
        (payload.get("email") or "").split("@", 1)[0],
    ]
    for raw in candidates:
        slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")[:30]
        if slug and slug[0].isalpha():
            return slug
    return "site-" + secrets.token_hex(4)


def _unique_slug(base: str) -> str:
    """Append -2 / -3 / … if the candidate is already used."""
    if not Tenant.objects.filter(schema_name=base).exists():
        return base
    i = 2
    while True:
        candidate = f"{base}-{i}"
        if not Tenant.objects.filter(schema_name=candidate).exists():
            return candidate
        i += 1


# pdf_export payload key -> Tenant field. Text business info synced from the
# user's pdf_export profile.
_PROFILE_FIELD_MAP = {
    "phone": "phone",
    "whatsapp": "whatsapp",
    "biz_email": "email",
    "address": "address",
    "instagram": "instagram",
    "tiktok": "tiktok",
    "snapchat": "snapchat",
    "tagline": "tagline",
    "brand_color": "primary_color",
}


def _download_logo(tenant, logo_url):
    """Fetch the pdf_export logo into the tenant's logo field (only if it has none)."""
    if not logo_url or tenant.logo:
        return False
    try:
        req = urllib.request.Request(logo_url, headers={"User-Agent": "tenant-cars-sso"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        if not data or len(data) > 8_000_000:
            return False
        ext = (logo_url.split("?")[0].rsplit(".", 1)[-1] or "png").lower()
        if ext not in ("png", "jpg", "jpeg", "webp", "gif"):
            ext = "png"
        tenant.logo.save(f"{tenant.schema_name}_logo.{ext}", ContentFile(data), save=False)
        return True
    except Exception:
        log.warning("SSO logo fetch failed for %s", tenant.schema_name, exc_info=True)
        return False


def _sync_business_info(tenant, payload, created):
    """Apply pdf_export business info onto the tenant.

    - name always tracks the payload's business_name.
    - other text fields are set on creation, otherwise only fill blanks (never
      clobber edits the owner made in Site Settings).
    - logo is downloaded only when the tenant has none yet.
    Busts the branding/home caches if anything changed.
    """
    changed = []
    desired_name = (payload.get("business_name") or "").strip()[:100]
    if desired_name and tenant.name != desired_name:
        tenant.name = desired_name
        changed.append("name")
    for src, field in _PROFILE_FIELD_MAP.items():
        val = (payload.get(src) or "").strip()
        if not val:
            continue
        current = getattr(tenant, field, "") or ""
        if (created or not current) and current != val:
            setattr(tenant, field, val[:200] if field != "primary_color" else val[:20])
            changed.append(field)
    if _download_logo(tenant, (payload.get("logo_url") or "").strip()):
        changed.append("logo")
    if changed:
        tenant.save()
        from django.core.cache import cache as _cache
        for _k in (
            f"tenant_branding:{tenant.schema_name}",
            f"home_html_v9:{tenant.schema_name}",
            f"home_ctx_v9:{tenant.schema_name}",
        ):
            _cache.delete(_k)
    return changed


@require_GET
def launch(request):
    """Verify the signed token from pdf_export and provision the user's site."""
    secret = getattr(settings, "SSO_SHARED_SECRET", "")
    if not secret:
        return _bad(request, "SSO_SHARED_SECRET is not configured on this server.", status=500)

    token = request.GET.get("token", "")
    if not token:
        return _bad(request, "رابط الدخول غير صحيح أو ينقصه رمز الإذن.")

    signer = TimestampSigner(key=secret, salt=SSO_SALT)
    try:
        raw = signer.unsign(token, max_age=SSO_MAX_AGE)
    except SignatureExpired:
        return _bad(request, "انتهت صلاحية الرابط. حاول من جديد من لوحة الإكسبورت.")
    except BadSignature:
        return _bad(request, "توقيع غير صالح. هذا الرابط لم يأت من مصدر موثوق.")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return _bad(request, "تنسيق الحمولة غير صالح.")

    email = (payload.get("email") or "").strip().lower()
    if not email:
        return _bad(request, "البريد الإلكتروني مفقود من الحمولة.")

    business_name = (payload.get("business_name") or "").strip() or payload.get("username", "موقع جديد")

    # ── Public-schema user (creates a row in the platform's auth_user) ──
    # `update_or_create` keyed on email keeps subsequent visits idempotent.
    user, _ = User.objects.update_or_create(
        email=email,
        defaults={
            "username": (payload.get("username") or email.split("@", 1)[0])[:150],
        },
    )
    user.backend = "django.contrib.auth.backends.ModelBackend"

    # ── Find or provision the tenant ────────────────────────────────────
    tenant = Tenant.objects.filter(owner=user).first()
    was_created = tenant is None
    domain = None
    if tenant is None:
        slug = _unique_slug(_slugify_owner(payload))
        apex = getattr(settings, "TENANT_APEX_DOMAIN", "")
        if not apex:
            return _bad(request, "TENANT_APEX_DOMAIN غير معرَّف على الخادم.", status=500)

        tenant = Tenant.objects.create(
            schema_name=slug,
            name=business_name[:100],
            owner=user,
            primary_color="#2563eb",
            secondary_color="#1e3a8a",
            accent_color="#3b82f6",
        )
        domain = Domain.objects.create(
            domain=f"{slug}.{apex}",
            tenant=tenant,
            is_primary=True,
        )

        # Create a tenant-side superuser with the same email so they can
        # actually log into /admin/ once they land. We set a random password
        # — the user will log in with their email + a password reset.
        with schema_context(tenant.schema_name):
            tenant_user, created = User.objects.update_or_create(
                username=user.username[:150],
                defaults={
                    "email": email,
                    "first_name": "",
                    "is_staff": True,
                    "is_superuser": True,
                    "is_active": True,
                },
            )
            if created:
                tenant_user.password = make_password(secrets.token_urlsafe(24))
                tenant_user.save(update_fields=["password"])
    else:
        domain = tenant.domains.filter(is_primary=True).first()

    # ── Sync business info from pdf_export (name always; other fields on
    # creation or to fill blanks; logo if none) and bust caches ──
    _sync_business_info(tenant, payload, created=was_created)

    # ── Log them in on the PUBLIC schema (so they can see the
    # cross-tenant launcher / admin if any) and bounce to their site ──
    login(request, user)
    target = f"https://{domain.domain}/" if domain else "/"
    return HttpResponseRedirect(target)
