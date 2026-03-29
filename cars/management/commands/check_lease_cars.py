"""
check_lease_cars
================
One-time post-import cleanup: query the Encar lease succession API in batches
and DELETE any car that is a lease vehicle (cannot be resold/exported).

Run this once right after every import — NOT on a recurring schedule.

The lease API is a batch endpoint:
  GET https://api.encar.com/legacy/usedcar/lease/car/succession?carIds=1,2,3,...
  → returns ONLY the cars that have an active lease (absent = not a lease car)

One request per 500 cars, so for 220,000 cars → ~440 requests total, ~1-2 min.

Usage:
  python manage.py check_lease_cars               # production
  python manage.py check_lease_cars --dry-run     # preview only
  python manage.py check_lease_cars --batch 200   # smaller API batches
"""

import json
import time
import urllib.request
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context, get_public_schema_name

from cars.models import ApiCar

_LEASE_URL = "https://api.encar.com/legacy/usedcar/lease/car/succession?carIds={ids}"
_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9",
    "origin": "https://fem.encar.com",
    "referer": "https://fem.encar.com/",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
}


def _query_lease_batch(lot_numbers, timeout):
    """
    Send one request for up to `batch` lot_numbers (= Encar carIds).
    Returns a set of lot_numbers (int) that ARE lease cars.
    On any error returns an empty set — safe to skip.
    """
    ids_str = ",".join(str(n) for n in lot_numbers)
    url = _LEASE_URL.format(ids=ids_str)
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return {item["carId"] for item in data}
    except Exception:
        return set()


def _delete_batch(ids, public_schema):
    """Raw SQL delete — bypasses ORM cross-schema FK cascade issues."""
    from django.db import connection
    with schema_context(public_schema):
        with connection.cursor() as cur:
            cur.execute(
                "DELETE FROM cars_wishlist WHERE car_id = ANY(%s)",
                [list(ids)],
            )
            cur.execute(
                "DELETE FROM cars_apicar WHERE id = ANY(%s)",
                [list(ids)],
            )


def _bust_cache():
    try:
        from django_redis import get_redis_connection
        con = get_redis_connection("default")
        for pattern in ("car_list:*", "home_html:*", "home_ctx:*", "landing_html:*"):
            keys = con.keys(pattern)
            if keys:
                con.delete(*keys)
        return
    except Exception:
        pass
    cache.clear()


class Command(BaseCommand):
    help = "Delete lease cars from Encar — run once after every import."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch",
            type=int,
            default=100,
            help="Number of lot_numbers per API request (default: 100, max ~100 before HTTP 414).",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=10,
            help="HTTP timeout per request in seconds (default: 10).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be deleted without touching the DB.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch"]
        timeout = options["timeout"]
        dry_run = options["dry_run"]

        public_schema = get_public_schema_name()

        # Load all cars that have a lot_number — map lot_number(int) → db id
        self.stdout.write("Loading cars from DB...", ending="\n")
        self.stdout.flush()
        lot_to_id = {}
        with schema_context(public_schema):
            qs = (
                ApiCar.objects
                .filter(status="available")
                .exclude(lot_number__isnull=True)
                .exclude(lot_number="")
                .values("id", "lot_number")
            )
            rows = list(qs)  # single fast query, no iterator chunking overhead

        for row in rows:
            try:
                lot_to_id[int(row["lot_number"])] = row["id"]
            except (ValueError, TypeError):
                pass

        self.stdout.write(f"Loaded {len(lot_to_id):,} cars from DB.")
        self.stdout.flush()

        total_cars = len(lot_to_id)
        all_lots = list(lot_to_id.keys())
        self.stdout.write(f"Checking {total_cars:,} cars for lease status (batch={batch_size})...")
        self.stdout.flush()

        lease_ids = []       # DB ids of lease cars to delete
        total_deleted = 0
        batches_done = 0
        t0 = time.time()

        for i in range(0, len(all_lots), batch_size):
            chunk = all_lots[i : i + batch_size]
            lease_lot_numbers = _query_lease_batch(chunk, timeout)
            batches_done += 1

            for lot_num in lease_lot_numbers:
                db_id = lot_to_id.get(lot_num)
                if db_id:
                    lease_ids.append(db_id)
                    self.stdout.write(f"  lease → lot={lot_num}  id={db_id}")

            # Progress every 10 batches
            if batches_done % 10 == 0:
                elapsed = time.time() - t0
                cars_checked = min(i + batch_size, total_cars)
                self.stdout.write(
                    f"  {cars_checked:,}/{total_cars:,} checked — "
                    f"{len(lease_ids)} lease found so far — "
                    f"{elapsed:.0f}s elapsed"
                )
                self.stdout.flush()

        # Delete all lease cars in one shot
        if lease_ids:
            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f"\n[DRY-RUN] Would delete {len(lease_ids)} lease cars."
                    )
                )
            else:
                _delete_batch(lease_ids, public_schema)
                _bust_cache()
                total_deleted = len(lease_ids)
                self.stdout.write(
                    self.style.SUCCESS(f"\n✓ Deleted {total_deleted} lease cars.")
                )
        else:
            self.stdout.write(self.style.SUCCESS("\n✓ No lease cars found."))

        elapsed = time.time() - t0
        self.stdout.write(
            self.style.SUCCESS(
                f"=== Done in {elapsed:.0f}s === "
                f"checked={total_cars:,} "
                f"lease_deleted={total_deleted}"
            )
        )
