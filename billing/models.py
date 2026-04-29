from django.db import models
from django.utils import timezone

from tenants.models import Tenant


class Subscription(models.Model):
    """One Stripe subscription per non-public tenant. $400/month."""

    STATUS_ACTIVE     = "active"
    STATUS_TRIALING   = "trialing"
    STATUS_PAST_DUE   = "past_due"
    STATUS_UNPAID     = "unpaid"
    STATUS_CANCELED   = "canceled"
    STATUS_INCOMPLETE = "incomplete"
    STATUS_INCOMPLETE_EXPIRED = "incomplete_expired"
    STATUS_NONE       = "none"  # never subscribed

    STATUS_CHOICES = [
        (STATUS_NONE, "Not subscribed"),
        (STATUS_INCOMPLETE, "Incomplete"),
        (STATUS_INCOMPLETE_EXPIRED, "Incomplete (expired)"),
        (STATUS_TRIALING, "Trialing"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAST_DUE, "Past due"),
        (STATUS_UNPAID, "Unpaid"),
        (STATUS_CANCELED, "Canceled"),
    ]

    GRANTED_STATUSES = {STATUS_ACTIVE, STATUS_TRIALING}

    tenant = models.OneToOneField(
        Tenant, on_delete=models.CASCADE, related_name="subscription"
    )
    stripe_customer_id     = models.CharField(max_length=64, blank=True, default="")
    stripe_subscription_id = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=24, choices=STATUS_CHOICES, default=STATUS_NONE
    )
    current_period_end = models.DateTimeField(blank=True, null=True)
    cancel_at_period_end = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.tenant.schema_name}: {self.status}"

    @property
    def is_active(self):
        if self.status not in self.GRANTED_STATUSES:
            return False
        # If we have a period end and it's in the past, deny access until
        # Stripe reports the renewal — protects against missed webhooks.
        if self.current_period_end and self.current_period_end < timezone.now():
            return False
        return True
