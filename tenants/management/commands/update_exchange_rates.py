from decimal import Decimal

import requests
from django.core.management.base import BaseCommand, CommandError

from tenants.models import GlobalExchangeRates


API_URL = "https://open.er-api.com/v6/latest/KRW"
FIELD_MAP = {
    "USD": "rate_usd",
    "SAR": "rate_sar",
    "AED": "rate_aed",
    "EUR": "rate_eur",
}


class Command(BaseCommand):
    help = "Fetch latest KRW-based exchange rates and update the global singleton (shared by all tenants)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and print rates without writing to the database.",
        )

    def handle(self, *args, **opts):
        try:
            resp = requests.get(API_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise CommandError(f"Failed to fetch exchange rates: {e}")

        if data.get("result") != "success":
            raise CommandError(f"API returned error: {data!r}")

        rates = data.get("rates") or {}
        updates = {}
        for code, field in FIELD_MAP.items():
            if code not in rates:
                self.stdout.write(self.style.WARNING(f"Missing {code} in API response; skipping."))
                continue
            updates[field] = Decimal(str(rates[code])).quantize(Decimal("0.000001"))

        if not updates:
            raise CommandError("No usable rates returned from API.")

        self.stdout.write(f"Rates (per 1 KRW): {updates}")

        if opts["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Dry run — no changes written."))
            return

        obj = GlobalExchangeRates.get_solo()
        for field, value in updates.items():
            setattr(obj, field, value)
        obj.save()
        self.stdout.write(self.style.SUCCESS("Updated global exchange rates."))
