"""Helpers for talking to Stripe.

We import stripe lazily so the codebase still loads in environments where
the package isn't installed yet (e.g. during initial migration).
"""
from django.conf import settings


def get_stripe():
    import stripe
    if not settings.STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def ensure_customer(subscription, tenant):
    """Create (or reuse) a Stripe Customer for this tenant."""
    if subscription.stripe_customer_id:
        return subscription.stripe_customer_id
    stripe = get_stripe()
    customer = stripe.Customer.create(
        email=tenant.email or None,
        name=tenant.name,
        metadata={"tenant_schema": tenant.schema_name, "tenant_id": str(tenant.id)},
    )
    subscription.stripe_customer_id = customer.id
    subscription.save(update_fields=["stripe_customer_id", "updated_at"])
    return customer.id
