"""Import car parts/accessories from the Autowini wholesale API into ShopItem.

Per-tenant via django-tenants:
    python manage.py tenant_command import_autowini --schema=<schema> --pages 5
    python manage.py tenant_command import_autowini --schema=<schema> --pages 3 --dry-run
    python manage.py tenant_command import_autowini --schema=<schema> --fitting TRUCK --no-images

Pulls Autowini's public parts feed (Korean OEM/used/rebuilt), maps condition →
origin+condition, auto-classifies kind (accessory vs part) from the category,
and upserts by listingId so re-runs update instead of duplicating.
"""
from django.core.management.base import BaseCommand

from site_shop.importer import import_autowini


class Command(BaseCommand):
    help = "Import parts/accessories from the Autowini API into ShopItem."

    def add_arguments(self, parser):
        parser.add_argument("--pages", type=int, default=3, help="How many pages (32 items each)")
        parser.add_argument("--start-page", type=int, default=1)
        parser.add_argument("--fitting", default="CAR", help="CAR / TRUCK / BUS")
        parser.add_argument("--currency", default="USD")
        parser.add_argument("--source", default="autowini")
        parser.add_argument("--no-images", action="store_true")
        parser.add_argument("--limit", type=int, default=5000)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        res = import_autowini(
            pages=opts["pages"], start_page=opts["start_page"], fitting=opts["fitting"],
            currency=opts["currency"], source=opts["source"],
            download_images=not opts["no_images"], limit=opts["limit"], dry_run=opts["dry_run"],
        )
        if res.get("dry_run"):
            self.stdout.write(self.style.SUCCESS(f"[dry-run] fetched {res['fetched']} rows"))
            for r in res["sample"]:
                self.stdout.write(f"  {r['kind']:9} | {r['part_number']:14} | {r['origin'] or '-':11} | {r['condition']:4} | {r['name'][:50]}")
        else:
            self.stdout.write(self.style.SUCCESS(
                f"created={res['created']} updated={res['updated']} "
                f"skipped={res['skipped']} images={res['images']}"))
            for e in res["errors"][:5]:
                self.stdout.write(self.style.WARNING(e))
