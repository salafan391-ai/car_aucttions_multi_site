"""Browse assistant usage at /admin/ (public schema — platform owner only).

Read-only: this is a log, not something to hand-edit. The list already shows the
total count at the top, filters by tenant/status/date, and searches question text.
"""
from django.contrib import admin

from .models import AssistantQuery


@admin.register(AssistantQuery)
class AssistantQueryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "schema_name", "username", "status", "short_question")
    list_filter = ("status", "schema_name", "created_at")
    search_fields = ("question", "answer", "username", "schema_name")
    date_hierarchy = "created_at"
    readonly_fields = (
        "schema_name", "username", "is_site_admin",
        "question", "answer", "status", "created_at",
    )

    @admin.display(description="question")
    def short_question(self, obj):
        return obj.question[:80]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # view-only
