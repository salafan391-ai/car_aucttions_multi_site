"""Telegram webhook — receives ofleet0_bot updates and links a dealer's chat."""
import json

from django.conf import settings
from django.http import Http404, HttpResponse
from django.views.decorators.csrf import csrf_exempt

from . import telegram_bot as tg


@csrf_exempt
def telegram_webhook(request, secret):
    if not settings.TELEGRAM_WEBHOOK_SECRET or secret != settings.TELEGRAM_WEBHOOK_SECRET:
        raise Http404
    try:
        update = json.loads((request.body or b"").decode() or "{}")
    except Exception:
        return HttpResponse("ok")
    msg = update.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    text = (msg.get("text") or "").strip()
    if chat_id and text.startswith("/start"):
        parts = text.split(maxsplit=1)
        tid = tg.verify_connect_token(parts[1] if len(parts) > 1 else "")
        if tid:
            from .models import Tenant
            Tenant.objects.filter(id=tid).update(telegram_chat_id=str(chat_id))
            tg.send_message(chat_id, "✅ تم ربط حسابك بنجاح.\nستصلك روابط السيارات التي ترسلها من «سلة الروابط» في لوحة التحكم هنا.")
        else:
            tg.send_message(chat_id, "مرحباً 👋\nلربط حسابك، افتح رابط الربط من صفحة «سلة الروابط» في لوحة التحكم.")
    return HttpResponse("ok")
