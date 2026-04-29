from django.contrib import admin

from .models import Subscription


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "tenant", "status", "current_period_end",
        "cancel_at_period_end", "stripe_subscription_id",
    )
    list_filter = ("status", "cancel_at_period_end")
    search_fields = (
        "tenant__schema_name", "tenant__name",
        "stripe_customer_id", "stripe_subscription_id",
    )
    readonly_fields = ("created_at", "updated_at")
