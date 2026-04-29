import datetime
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import connection
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from tenants.models import Tenant

from .models import Subscription
from .stripe_utils import ensure_customer, get_stripe

log = logging.getLogger(__name__)

# A successful payment buys 30 days of access. The amount is per-tenant
# (see Tenant.billing_amount_usd, defaults to $400).
PAID_PERIOD_DAYS = 30
PRICE_CURRENCY = "usd"
PRICE_LABEL = "Monthly access"


def _amount_cents(tenant):
    """Convert the tenant's USD billing amount to integer cents for Stripe."""
    return int(round(float(tenant.billing_amount_usd) * 100))


def _amount_cents_from(amount_usd):
    return int(round(float(amount_usd) * 100))


def _current_tenant_or_none(request):
    tenant = getattr(connection, "tenant", None)
    if not tenant or tenant.schema_name == "public":
        return None
    return tenant


def _require_visible_tenant(request):
    """Return tenant if billing is visible for it; otherwise raise 404."""
    tenant = _current_tenant_or_none(request)
    if not tenant or not getattr(tenant, "billing_visible", False):
        raise Http404("Billing is not enabled for this site.")
    return tenant


def _get_or_create_subscription(tenant):
    sub, _ = Subscription.objects.get_or_create(tenant=tenant)
    return sub


def _absolute_url(request, path):
    return request.build_absolute_uri(path)


@staff_member_required
def billing_dashboard(request):
    tenant = _require_visible_tenant(request)
    subscription = _get_or_create_subscription(tenant)
    return render(
        request,
        "billing/dashboard.html",
        {
            "tenant": tenant,
            "subscription": subscription,
            "stripe_public_key": settings.STRIPE_PUBLIC_KEY,
            "price_amount": tenant.billing_amount_usd,
            "price_currency": "USD",
        },
    )


@staff_member_required
@require_POST
def create_checkout_session(request):
    tenant = _require_visible_tenant(request)
    subscription = _get_or_create_subscription(tenant)
    customer_id = ensure_customer(subscription, tenant)

    stripe = get_stripe()
    session = stripe.checkout.Session.create(
        mode="payment",
        customer=customer_id,
        line_items=[{
            "price_data": {
                "currency": PRICE_CURRENCY,
                "product_data": {
                    "name": f"{PRICE_LABEL} — {tenant.name}",
                },
                "unit_amount": _amount_cents(tenant),
            },
            "quantity": 1,
        }],
        success_url=_absolute_url(request, reverse("billing:success"))
            + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=_absolute_url(request, reverse("billing:dashboard")),
        client_reference_id=tenant.schema_name,
        metadata={"tenant_schema": tenant.schema_name, "tenant_id": str(tenant.id)},
        payment_intent_data={
            "metadata": {
                "tenant_schema": tenant.schema_name,
                "tenant_id": str(tenant.id),
            },
        },
        allow_promotion_codes=True,
    )
    return redirect(session.url)


@staff_member_required
def checkout_success(request):
    tenant = _require_visible_tenant(request)
    session_id = request.GET.get("session_id")
    if session_id:
        try:
            stripe = get_stripe()
            session = stripe.checkout.Session.retrieve(session_id)
            if session.get("payment_status") == "paid":
                sub = _get_or_create_subscription(tenant)
                _record_payment(sub)
        except Exception as exc:
            log.warning("checkout_success sync failed: %s", exc)

    messages.success(request, "تم استلام الدفعة. شكراً لك!")
    return redirect("billing:dashboard")


# ── Payment Link (SaaS-owner only) ─────────────────────────────────────────

@staff_member_required
@require_POST
def create_payment_link(request, tenant_id):
    """SaaS-owner only: generate a Stripe Payment Link for a specific tenant.

    The link can be sent to the tenant via WhatsApp/email. When they pay,
    Stripe fires the same checkout.session.completed webhook we already
    handle, with metadata.tenant_schema set so the right tenant is credited.
    """
    if connection.schema_name != "public":
        raise Http404()

    tenant = Tenant.objects.filter(pk=tenant_id).exclude(schema_name="public").first()
    if not tenant:
        raise Http404("Tenant not found.")

    raw_amount = (request.POST.get("amount") or "").strip()
    try:
        amount_usd = float(raw_amount) if raw_amount else float(tenant.billing_amount_usd)
    except ValueError:
        amount_usd = float(tenant.billing_amount_usd)
    if amount_usd < 0.5:
        messages.error(request, "Amount must be at least $0.50.")
        return redirect("home")

    Subscription.objects.get_or_create(tenant=tenant)

    payment_link = _build_payment_link(
        amount_usd=amount_usd,
        product_name=f"{PRICE_LABEL} — {tenant.name}",
        metadata={
            "tenant_schema": tenant.schema_name,
            "tenant_id": str(tenant.id),
        },
    )

    return render(request, "billing/payment_link.html", {
        "tenant": tenant,
        "amount_usd": amount_usd,
        "product_name": f"{PRICE_LABEL} — {tenant.name}",
        "payment_link": payment_link,
    })


@staff_member_required
@require_POST
def create_generic_payment_link(request):
    """SaaS-owner only: generate a Stripe Payment Link for an arbitrary
    amount and description — not tied to any tenant. Useful for one-off
    charges (consulting, setup fees, prospects who aren't a tenant yet).
    """
    if connection.schema_name != "public":
        raise Http404()

    raw_amount = (request.POST.get("amount") or "").strip()
    try:
        amount_usd = float(raw_amount)
    except ValueError:
        messages.error(request, "Invalid amount.")
        return redirect("home")
    if amount_usd < 0.5:
        messages.error(request, "Amount must be at least $0.50.")
        return redirect("home")

    description = (request.POST.get("description") or "").strip() or "One-off payment"

    payment_link = _build_payment_link(
        amount_usd=amount_usd,
        product_name=description,
        metadata={"source": "saas_owner_oneoff"},
    )

    return render(request, "billing/payment_link.html", {
        "tenant": None,
        "amount_usd": amount_usd,
        "product_name": description,
        "payment_link": payment_link,
    })


def _build_payment_link(*, amount_usd, product_name, metadata):
    stripe = get_stripe()
    return stripe.PaymentLink.create(
        line_items=[{
            "price_data": {
                "currency": PRICE_CURRENCY,
                "product_data": {"name": product_name},
                "unit_amount": _amount_cents_from(amount_usd),
            },
            "quantity": 1,
        }],
        metadata=metadata,
        payment_intent_data={"metadata": metadata},
    )


# ── Webhook ────────────────────────────────────────────────────────────────

def _record_payment(local_sub):
    """Mark the tenant as paid for the next PAID_PERIOD_DAYS days."""
    now = timezone.now()
    base = local_sub.current_period_end if (
        local_sub.current_period_end and local_sub.current_period_end > now
    ) else now
    local_sub.current_period_end = base + datetime.timedelta(days=PAID_PERIOD_DAYS)
    local_sub.status = Subscription.STATUS_ACTIVE
    local_sub.save(update_fields=["current_period_end", "status", "updated_at"])


def _find_subscription_for_session(session):
    """Resolve a Stripe Checkout Session to a local Subscription row."""
    schema = (session.get("metadata") or {}).get("tenant_schema")
    if schema:
        tenant = Tenant.objects.filter(schema_name=schema).first()
        if tenant:
            sub, _ = Subscription.objects.get_or_create(tenant=tenant)
            return sub

    customer = session.get("customer")
    customer_id = customer if isinstance(customer, str) else (customer or {}).get("id")
    if customer_id:
        return Subscription.objects.filter(stripe_customer_id=customer_id).first()

    return None


@csrf_exempt
@require_POST
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    secret = settings.STRIPE_WEBHOOK_SECRET

    if not secret:
        log.error("STRIPE_WEBHOOK_SECRET not configured — refusing webhook")
        return HttpResponse(status=500)

    stripe = get_stripe()

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except ValueError:
        return HttpResponseBadRequest("Invalid payload")
    except stripe.error.SignatureVerificationError:
        return HttpResponseBadRequest("Invalid signature")

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        if data.get("payment_status") == "paid":
            local = _find_subscription_for_session(data)
            if local:
                _record_payment(local)

    return JsonResponse({"received": True})
