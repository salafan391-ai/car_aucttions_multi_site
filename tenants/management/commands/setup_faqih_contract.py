"""Populate the alfaqihcars tenant's buyer-contract settings to match the old
alfaqih website's brokerage contract, and load its stamp. Idempotent."""
import os

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from tenants.models import Tenant

VALUES = {
    "contract_enabled": True,
    "contract_party1": "أبوبكر علي عبدالله الفقيه إدارة وتنشيط المبيعات",
    "contract_bank": "الراجحي",
    "contract_commission": "2250",
    "contract_clearance_org": "الخطوة السريعة للتخليص الجمركي",
    "contract_clearance_license": "5663",
    "contract_default_region": "korea",
    "contract_default_port": "جدة",
    "contract_import_days": "45 إلى 60",
    "contract_phone": "0558007721",
    "contract_email": "alfaqih.cars.2025@gmail.com",
}


class Command(BaseCommand):
    help = "Configure the alfaqihcars buyer contract + stamp."

    def add_arguments(self, parser):
        parser.add_argument("--schema", default="alfaqihcars")

    def handle(self, *args, **o):
        try:
            t = Tenant.objects.get(schema_name=o["schema"])
        except Tenant.DoesNotExist:
            raise CommandError(f"Tenant {o['schema']} not found.")
        for k, v in VALUES.items():
            setattr(t, k, v)
        if not t.contract_stamp:
            stamp = os.path.join(settings.BASE_DIR, "site_cars", "static", "site_cars", "img", "faqih_stamp.png")
            if os.path.exists(stamp):
                with open(stamp, "rb") as f:
                    t.contract_stamp.save("faqih_stamp.png", File(f), save=False)
                self.stdout.write("stamp loaded")
            else:
                self.stdout.write(self.style.WARNING(f"stamp not found at {stamp}"))
        t.save()
        self.stdout.write(self.style.SUCCESS(
            f"Contract configured for {t.schema_name} (enabled={t.contract_enabled}, stamp={'yes' if t.contract_stamp else 'no'})"))
