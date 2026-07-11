"""ofleet0_bot helper: connect a dealer's Telegram chat + push car links to it.

Connect flow: the dashboard shows a deep link
``https://t.me/<bot>?start=<connect_token>``. The dealer taps it, Telegram
sends ``/start <token>`` to the bot, our webhook verifies the token (an
HMAC of the tenant id — no storage, Telegram-safe chars) and stores the
chat id on the tenant. Then the share cart can send each car to that chat.
"""
import hashlib
import hmac
import time

import requests
from django.conf import settings

_API = "https://api.telegram.org/bot{token}/{method}"


def _token():
    return (getattr(settings, "TELEGRAM_BOT_TOKEN", "") or "").strip()


def is_configured():
    return bool(_token())


def bot_username():
    return (getattr(settings, "TELEGRAM_BOT_USERNAME", "") or "").strip().lstrip("@")


def connect_token(tenant_id):
    """Telegram-safe (A-Za-z0-9_-) self-contained token: '<id>_<hmac16>'."""
    sig = hmac.new(settings.SECRET_KEY.encode(), f"tg:{tenant_id}".encode(),
                   hashlib.sha256).hexdigest()[:16]
    return f"{tenant_id}_{sig}"


def verify_connect_token(token):
    try:
        tid, sig = (token or "").rsplit("_", 1)
        exp = hmac.new(settings.SECRET_KEY.encode(), f"tg:{tid}".encode(),
                       hashlib.sha256).hexdigest()[:16]
        if hmac.compare_digest(sig, exp):
            return int(tid)
    except Exception:
        pass
    return None


def _call(method, **data):
    if not _token():
        return None
    url = _API.format(token=_token(), method=method)
    # Retry on 429 (bulk sends to one chat get throttled) honouring retry_after.
    for attempt in range(3):
        try:
            r = requests.post(url, json=data, timeout=15)
            body = r.json()
        except Exception:
            return None
        if r.status_code == 429 and attempt < 2:
            wait = ((body.get("parameters") or {}).get("retry_after") or 1)
            time.sleep(min(wait, 5))
            continue
        return body
    return body


def get_chat(chat_id):
    """Fetch chat info (first/last name, username) for a connected chat id."""
    body = _call("getChat", chat_id=chat_id) or {}
    return body.get("result") or {}


def send_message(chat_id, text):
    return _call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML")


def send_photo(chat_id, photo, caption):
    return _call("sendPhoto", chat_id=chat_id, photo=photo, caption=caption, parse_mode="HTML")


def set_webhook(base_url):
    """base_url e.g. https://general-cars.com — sets the fixed webhook."""
    secret = (getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "") or "").strip()
    url = f"{base_url.rstrip('/')}/telegram/webhook/{secret}/"
    return _call("setWebhook", url=url, allowed_updates=["message"])
