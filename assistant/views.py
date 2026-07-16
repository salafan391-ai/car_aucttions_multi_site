"""The dashboard help assistant endpoint.

Docs-grounded only: this view reads a static guide and the asking user's role.
It never touches tenant data, so there is nothing here that can leak across
schemas. Keep it that way — if this ever grows data access, every query must be
scoped to `connection.schema_name`.
"""
import datetime as dt
import logging

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.shortcuts import render
from django.views.decorators.http import require_POST

from site_cars.permissions import is_site_admin, staff_required

from .client import AssistantUnavailable, ask
from .models import AssistantQuery

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 500


def _record(request, question, answer, status):
    """Log one question. Best-effort — a logging failure must never break the
    answer the user is waiting for."""
    try:
        AssistantQuery.objects.create(
            schema_name=connection.schema_name,
            username=getattr(request.user, "username", "")[:150],
            is_site_admin=is_site_admin(request.user),
            question=question[:2000],
            answer=(answer or "")[:4000],
            status=status,
        )
    except Exception:  # noqa: BLE001 — telemetry must not surface to the user
        logger.exception("assistant: failed to record query")


def _over_limit(user) -> str | None:
    """Return an Arabic message if `user` is rate limited, else None.

    Two caps: a per-user burst cap (abuse), and a per-tenant daily cap (spend).
    These fail open if Redis is down — the cache is configured with
    IGNORE_EXCEPTIONS, so a cache outage degrades to no limiting rather than a
    dead assistant. That is the right trade for a help widget, but it means the
    daily cap is a budget guardrail, not a hard billing guarantee.
    """
    schema = connection.schema_name
    today = dt.date.today().isoformat()

    burst_key = f"assistant:burst:{schema}:{user.pk}"
    burst = cache.get(burst_key) or 0
    if burst >= settings.ASSISTANT_USER_BURST_PER_MIN:
        return "أرسلت أسئلة كثيرة بسرعة. انتظر دقيقة ثم حاول مرة أخرى."

    day_key = f"assistant:quota:{schema}:{today}"
    used = cache.get(day_key) or 0
    if used >= settings.ASSISTANT_TENANT_DAILY_LIMIT:
        logger.warning("assistant: daily cap hit for schema=%s", schema)
        return "تم الوصول إلى الحد اليومي لأسئلة المساعد لهذا الموقع."

    cache.set(burst_key, burst + 1, 60)
    cache.set(day_key, used + 1, 60 * 60 * 26)
    return None


@staff_required
@require_POST
def assistant_ask(request):
    """htmx target: renders just the answer bubble."""
    question = (request.POST.get("question") or "").strip()

    if not question:
        return render(request, "assistant/_answer.html", {"error": "اكتب سؤالك أولاً."})
    if len(question) > MAX_QUESTION_CHARS:
        return render(
            request,
            "assistant/_answer.html",
            {"error": f"السؤال طويل جداً (الحد {MAX_QUESTION_CHARS} حرف)."},
        )

    limited = _over_limit(request.user)
    if limited:
        # Recorded so demand that hit the cap is still visible in the stats,
        # not silently dropped.
        _record(request, question, limited, AssistantQuery.STATUS_RATE_LIMITED)
        return render(request, "assistant/_answer.html", {"error": limited})

    try:
        answer = ask(request.user, question)
    except AssistantUnavailable as exc:
        _record(request, question, str(exc), AssistantQuery.STATUS_ERROR)
        return render(request, "assistant/_answer.html", {"error": str(exc)})

    _record(request, question, answer, AssistantQuery.STATUS_OK)
    return render(
        request,
        "assistant/_answer.html",
        {"question": question, "answer": answer},
    )
