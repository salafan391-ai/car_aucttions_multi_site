"""Import a parts/accessories catalogue feed into ShopItem for one tenant.

Run per-tenant via django-tenants:
    python manage.py tenant_command import_shop_csv --schema=<schema> <file.csv> \
        --kind=part --source=autowini

Or from a URL:
    python manage.py tenant_command import_shop_csv --schema=<schema> \
        --url=https://supplier.example/feed.csv --kind=part --source=supplier
"""
from django.core.management.base import BaseCommand, CommandError

from site_shop.importer import import_csv_text, import_csv_url


class Command(BaseCommand):
    help = "Import a CSV catalogue feed into ShopItem (parts / accessories)."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", help="Path to a local CSV file")
        parser.add_argument("--url", help="Fetch the CSV from this URL instead")
        parser.add_argument("--kind", default="part", choices=["part", "accessory"],
                            help="Default kind for rows that don't specify one")
        parser.add_argument("--source", default="csv", help="Source label (used for upsert de-dup)")
        parser.add_argument("--currency", default="SAR", help="Default currency")
        parser.add_argument("--no-images", action="store_true", help="Skip downloading images")
        parser.add_argument("--limit", type=int, default=2000)

    def handle(self, *args, **opts):
        kwargs = dict(kind=opts["kind"], source=opts["source"],
                      default_currency=opts["currency"],
                      download_images=not opts["no_images"], limit=opts["limit"])
        if opts.get("url"):
            res = import_csv_url(opts["url"], **kwargs)
        elif opts.get("path"):
            with open(opts["path"], encoding="utf-8-sig", errors="replace") as f:
                res = import_csv_text(f.read(), **kwargs)
        else:
            raise CommandError("Provide a CSV file path or --url")

        self.stdout.write(self.style.SUCCESS(
            f"created={res['created']} updated={res['updated']} "
            f"skipped={res['skipped']} images={res['images']}"))
        for e in res["errors"]:
            self.stdout.write(self.style.WARNING(e))
