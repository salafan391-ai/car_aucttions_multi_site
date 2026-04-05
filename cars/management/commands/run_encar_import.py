import csv
import itertools
import os

import boto3
import requests
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.db import connection

from cars.models import ApiCar


class Command(BaseCommand):
    help = "Delete stale Encar cars first, then import fresh data from R2"

    def handle(self, *args, **options):
        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )

        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": "encar-csv", "Key": "encar/encar_cars.csv"},
            ExpiresIn=3600,
        )

        # ── Step 1: Quick pass to collect all lot numbers in the CSV ──────────
        self.stdout.write("Scanning CSV for lot numbers...")
        seen: set[str] = set()
        try:
            resp = requests.get(url, stream=True, timeout=60)
            resp.encoding = "utf-8"
            lines = (line for line in resp.iter_lines(decode_unicode=True) if line)
            header_line = next(lines, "").lstrip("\ufeff")
            delimiter = "," if header_line.count(",") >= header_line.count("|") else "|"
            reader = csv.DictReader(itertools.chain([header_line], lines), delimiter=delimiter)
            for row in reader:
                ln = (row.get("inner_id") or row.get("id") or "").strip()
                if ln:
                    seen.add(ln)
            resp.close()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to scan CSV: {e}"))
            return

        self.stdout.write(f"CSV contains {len(seen):,} lot numbers.")

        # ── Step 2: Delete stale cars using Django ORM ────────────────────────
        self.stdout.write("Finding stale cars...")
        db_lots = set(
            ApiCar.objects.filter(category__isnull=True).values_list("lot_number", flat=True)
        )
        stale = db_lots - seen
        self.stdout.write(f"Deleting {len(stale):,} stale cars...")

        # Find all tenant schemas dynamically
        from django_tenants.utils import get_tenant_model
        tenant_schemas = list(
            get_tenant_model().objects
            .exclude(schema_name="public")
            .values_list("schema_name", flat=True)
        )

        CHUNK = 3000
        stale_list = list(stale)
        total_deleted = 0
        with connection.cursor() as cursor:
            for i in range(0, len(stale_list), CHUNK):
                chunk = stale_list[i : i + CHUNK]

                # Delete from public-schema tables first
                cursor.execute(
                    "DELETE FROM cars_wishlist WHERE car_id IN (SELECT id FROM cars_apicar WHERE lot_number = ANY(%s))",
                    [chunk],
                )
                cursor.execute(
                    "DELETE FROM cars_carimage WHERE car_id IN (SELECT id FROM cars_apicar WHERE lot_number = ANY(%s))",
                    [chunk],
                )

                # Delete from all tenant-schema tables
                for schema in tenant_schemas:
                    for table in ("site_cars_siterating", "site_cars_sitequestion", "site_cars_siteorder", "site_cars_sitesoldcar"):
                        cursor.execute(
                            f"DELETE FROM {schema}.{table} WHERE car_id IN (SELECT id FROM cars_apicar WHERE lot_number = ANY(%s))",
                            [chunk],
                        )

                cursor.execute(
                    "DELETE FROM cars_apicar WHERE lot_number = ANY(%s)",
                    [chunk],
                )
                total_deleted += cursor.rowcount

        self.stdout.write(self.style.SUCCESS(f"Deleted {total_deleted:,} stale cars."))

        # ── Step 3: Import fresh data ─────────────────────────────────────────
        self.stdout.write("Starting import...")
        call_command(
            "import_encar_fast",
            url=url,
            delete_stale=False,
            progress=True,
            progress_every=5000,
        )
