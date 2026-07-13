"""
Daily Encar import wrapper.

Fast strategy (mirrors alokar-main, adapted for django-tenants)
---------------------------------------------------------------
1. Download today's CSV from R2 ONCE to local disk via boto3 multipart
   (parallel 16 MB parts + adaptive retries). This handles R2's per-connection
   ~80 MB drop quirk and is far faster than streaming with requests.
2. Hand the local file to import_encar_fast via a `file://` URL. It makes a
   SINGLE local pass that upserts every active row AND deletes stale cars
   (lot_number not seen in the CSV) using the lot numbers gathered during that
   same pass — via a temp-table delete that is aware of every tenant schema.

This replaces the old flow that streamed the 2.9 GB CSV over the network twice
(once to scan for lot numbers, once to import) and parsed it twice in Python.
Now: one parallel download, one local parse pass.

Required env vars: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
"""
import os
import tempfile
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.utils import timezone

from cars.models import ApiCar


class Command(BaseCommand):
    help = "Download today's Encar CSV from R2 once, then upsert + delete stale in a single local pass."

    def handle(self, *args, **options):
        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
            config=Config(
                retries={"max_attempts": 20, "mode": "adaptive"},
                read_timeout=120,
                connect_timeout=30,
            ),
        )
        # Multipart split → each 16 MB part is independently retryable, so a
        # transient R2 drop mid-file doesn't fail the whole download.
        transfer_cfg = TransferConfig(
            multipart_threshold=16 * 1024 * 1024,
            multipart_chunksize=16 * 1024 * 1024,
            max_concurrency=4,
            use_threads=True,
        )

        # IMPORTANT: write to disk, NOT the default /tmp — on some hosts /tmp is a
        # RAM-backed tmpfs, so a ~3 GB CSV there would consume RAM and, alongside
        # the local Postgres upsert, OOM the box. /var/tmp is disk-backed.
        tmp_base = os.environ.get("ENCAR_TMPDIR") or "/var/tmp"
        with tempfile.TemporaryDirectory(prefix="encar-import-", dir=tmp_base) as tmpdir:
            local_csv = Path(tmpdir) / "encar_cars.csv"

            # ── Step 1: Download CSV to local disk (resumable, drop-resistant) ──
            self.stdout.write(f"Downloading CSV from R2 to {local_csv}...")
            s3.download_file(
                Bucket="encar-csv",
                Key="encar/encar_cars.csv",
                Filename=str(local_csv),
                Config=transfer_cfg,
            )
            size_mb = local_csv.stat().st_size / 1024 / 1024
            self.stdout.write(self.style.SUCCESS(f"Downloaded {size_mb:,.1f} MB"))

            # ── Step 2: Clear previous is_new flags before importing ───────────
            cleared = ApiCar.objects.filter(is_new=True).update(is_new=False)
            self.stdout.write(f"Cleared is_new flag on {cleared:,} cars from previous import.")

            import_started_at = timezone.now()

            # ── Step 3: Single local pass — upsert all rows AND delete stale ───
            # import_encar_fast collects every lot_number it sees, then (with
            # delete_stale) removes ApiCars not in the CSV via a temp-table join
            # that also clears references in each tenant schema. No separate scan.
            self.stdout.write(f"Importing from {local_csv} (upsert + stale delete)...")
            call_command(
                "import_encar_fast",
                url=f"file://{local_csv}",
                delete_stale=True,
                progress=True,
                progress_every=5000,
                chunk_size=5000,
                update_batch_size=1000,
            )

            # ── Step 4: Mark freshly imported cars as new ─────────────────────
            marked = ApiCar.objects.filter(created_at__gte=import_started_at).update(is_new=True)
            self.stdout.write(self.style.SUCCESS(f"Marked {marked:,} newly imported cars as new."))
