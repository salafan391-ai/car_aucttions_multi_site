"""Usage log for the dashboard help assistant.

`assistant` is a SHARED_APP, so this table lives in the public schema only — one
row per question across every tenant. That's deliberate: it makes "how many times
and what" answerable in one place. The tenant a question came from is recorded in
`schema_name`, since the ORM write itself routes to the shared/public table
regardless of which tenant context the view ran in.

Note on privacy: this stores the free text a staff member typed. It's internal
"how do I…" help usage, not customer data, but it is retained — prune it if that
ever matters (see the `assistant_stats --prune` command).
"""
from django.db import models


class AssistantQuery(models.Model):
    STATUS_OK = "ok"
    STATUS_ERROR = "error"
    STATUS_RATE_LIMITED = "rate_limited"
    STATUS_CHOICES = [
        (STATUS_OK, "answered"),
        (STATUS_ERROR, "error"),
        (STATUS_RATE_LIMITED, "rate limited"),
    ]

    schema_name = models.CharField(max_length=63, db_index=True)
    username = models.CharField(max_length=150, blank=True, default="")
    is_site_admin = models.BooleanField(default=False)
    question = models.TextField()
    # For an error/rate-limited row this holds the Arabic message the user saw.
    answer = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_OK, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "assistant query"
        verbose_name_plural = "assistant queries"

    def __str__(self):
        return f"[{self.schema_name}] {self.question[:60]}"
