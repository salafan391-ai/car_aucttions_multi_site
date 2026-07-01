"""Register (or show) the ofleet0_bot webhook.

The webhook lives at a single fixed URL — the bot delivers every dealer's
/start there, and we link the chat by the connect token. Run once after the
env vars (TELEGRAM_BOT_TOKEN / TELEGRAM_WEBHOOK_SECRET) are set, and again
whenever the public host changes.

    python manage.py set_telegram_webhook https://general-cars.com
"""
from django.core.management.base import BaseCommand, CommandError

from tenants import telegram_bot as tg


class Command(BaseCommand):
    help = "Set the Telegram bot webhook to <base_url>/telegram/webhook/<secret>/"

    def add_arguments(self, parser):
        parser.add_argument("base_url", help="Public https base, e.g. https://general-cars.com")

    def handle(self, *args, **opts):
        if not tg.is_configured():
            raise CommandError("TELEGRAM_BOT_TOKEN is not set.")
        base = opts["base_url"].strip()
        if not base.startswith("https://"):
            raise CommandError("base_url must start with https:// (Telegram requires TLS).")
        res = tg.set_webhook(base)
        if not res:
            raise CommandError("No response from Telegram (network/token error).")
        if res.get("ok"):
            self.stdout.write(self.style.SUCCESS(
                f"Webhook set: {base.rstrip('/')}/telegram/webhook/<secret>/  → {res.get('description', 'ok')}"))
        else:
            raise CommandError(f"Telegram rejected setWebhook: {res}")
