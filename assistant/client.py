"""Thin wrapper around the Anthropic Messages API for the help assistant."""
import logging
import os

import anthropic
from django.conf import settings

from .prompts import build_system_prompt

logger = logging.getLogger(__name__)

_client = None


class AssistantUnavailable(Exception):
    """Raised when we can't get an answer — carries an admin-facing Arabic message."""


def _api_key() -> str:
    """Resolve the key from settings, falling back to the live environment.

    settings_vps.py lives only on the VPS and calls load_dotenv() on
    /opt/tenant-cars/.env. If that ever runs *after* `from .settings import *`,
    settings.ANTHROPIC_API_KEY is baked as "" at import time even though the
    variable is present in the process later. Reading os.environ here as a
    fallback makes the assistant independent of that import ordering.
    """
    return (getattr(settings, "ANTHROPIC_API_KEY", "") or "").strip() or os.environ.get(
        "ANTHROPIC_API_KEY", ""
    ).strip()


def _get_client():
    global _client
    if _client is None:
        api_key = _api_key()
        if not api_key:
            raise AssistantUnavailable("المساعد غير مُفعَّل على هذا الموقع.")
        _client = anthropic.Anthropic(api_key=api_key, timeout=30.0, max_retries=2)
    return _client


def ask(user, question: str) -> str:
    """Answer `question` for `user`. Raises AssistantUnavailable on failure."""
    client = _get_client()
    try:
        response = client.messages.create(
            model=settings.ASSISTANT_MODEL,
            # Help answers are deliberately short; this caps a runaway response.
            max_tokens=1024,
            system=build_system_prompt(user),
            messages=[{"role": "user", "content": question}],
        )
    except anthropic.RateLimitError:
        logger.warning("assistant: upstream rate limit")
        raise AssistantUnavailable("المساعد مشغول حالياً، يرجى المحاولة بعد قليل.")
    except anthropic.APIStatusError as exc:
        logger.error("assistant: API error %s: %s", exc.status_code, exc.message)
        raise AssistantUnavailable("تعذّر الوصول إلى المساعد، يرجى المحاولة لاحقاً.")
    except anthropic.APIConnectionError:
        logger.error("assistant: connection error")
        raise AssistantUnavailable("تعذّر الاتصال بالمساعد، يرجى المحاولة لاحقاً.")

    if response.stop_reason == "refusal":
        raise AssistantUnavailable("لا يمكن الإجابة على هذا السؤال.")

    text = "\n".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    if not text:
        raise AssistantUnavailable("لم يصل رد من المساعد، يرجى المحاولة مرة أخرى.")

    logger.info(
        "assistant: in=%s cached=%s out=%s",
        response.usage.input_tokens,
        response.usage.cache_read_input_tokens,
        response.usage.output_tokens,
    )
    return text
