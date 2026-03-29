"""
check_encar_availability
========================
Checks every available car (with a lot_number) against the Encar public API
and DELETES it when Encar returns 404 (car no longer listed).

Cars live in the PUBLIC shared schema — we run ONCE, not per tenant.

Speed: uses a thread pool (default 10 workers) so many requests run in
parallel while staying gentle on Encar and the DB.

Usage:
  python manage.py check_encar_availability            # production
  python manage.py check_encar_availability --dry-run  # preview only
  python manage.py check_encar_availability --limit 200 --workers 5
"""

import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context, get_public_schema_name

from cars.models import ApiCar

_ENCAR_URL = "https://api.encar.com/v1/readside/inspection/vehicle/{lot}"
_HEADERS = {
    "accept": "*/*",
    "origin": "https://fem.encar.com",
    "referer": "https://fem.encar.com/",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def _bust_car_list_cache():
    """Clear car_list / home page caches so deleted cars disappear immediately."""
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


def _check_lot(args):
    """
    Worker function — runs inside a thread pool.
    Returns (car_id, 'gone' | 'ok' | 'unknown').
      gone    → 404 from Encar → car should be deleted
      ok      → 200 → still listed
      unknown → network error / 5xx / 429 → skip this run
    """
    car_id, lot_number, timeout = args
    url = _ENCAR_URL.format(lot=lot_number)
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return car_id, "ok" if resp.status == 200 else "unknown"
    except urllib.error.HTTPError as err:
        return car_id, "gone" if err.code == 404 else "unknown"
    except Exception:
        return car_id, "unknown"


def _delete_batch(ids, public_schema):
    """
    Delete a batch of ApiCar rows safely using raw SQL.

    Django's ORM .delete() triggers a cross-schema cascade lookup for
    tenant-schema tables (site_cars_siteorder, site_cars_siterating, etc.)
    which fails with 'relation does not exist' when the DB connection is
    pointing at the public schema.  Raw SQL bypasses ORM cascade entirely
    and lets PostgreSQL handle FK cascades at the DB level (or just deletes
    what exists in the public schema).
    """
    from django.db import connection
    ids_tuple = tuple(ids)
    with schema_context(public_schema):
        with connection.cursor() as cur:
            # 1. Remove wishlist references (public schema table)
            cur.execute(
                "DELETE FROM cars_wishlist WHERE car_id = ANY(%s)",
                [list(ids_tuple)],
            )
            # 2. Delete the cars — no ORM cascade, no cross-schema lookup
            cur.execute(
                "DELETE FROM cars_apicar WHERE id = ANY(%s)",
                [list(ids_tuple)],
            )


class Command(BaseCommand):
    help = (
        "Check Encar availability for all active cars and DELETE those no longer listed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--workers",
            type=int,
            default=20,
            help="Parallel HTTP workers (default: 20).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Max cars to check in one run (0 = unlimited, checks all).",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=7,
            help="HTTP timeout per request in seconds (default: 7).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Delete batch size (default: 100).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without touching the DB.",
        )

    def handle(self, *args, **options):
        workers = options["workers"]
        limit = options["limit"]
        timeout = options["timeout"]
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]

        public_schema = get_public_schema_name()

        with schema_context(public_schema):
            qs = (
                ApiCar.objects
                .filter(status="available")
                .exclude(lot_number__isnull=True)
                .exclude(lot_number="")
                .only("id", "lot_number")
            )
            if limit:
                qs = qs[:limit]
            tasks = [(car.id, car.lot_number, timeout) for car in qs.iterator(chunk_size=500)]

        total = len(tasks)
        self.stdout.write(f"Checking {total} cars with {workers} workers (dry_run={dry_run})...")

        checked = 0
        gone_ids = []
        total_deleted = 0
        unknown = 0
        t0 = time.time()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_check_lot, task): task for task in tasks}
            for future in as_completed(futures):
                car_id, result = future.result()
                checked += 1

                if result == "gone":
                    gone_ids.append(car_id)
                    self.stdout.write(f"  gone → id={car_id}")
                elif result == "unknown":
                    unknown += 1

                # Flush delete batch
                if not dry_run and len(gone_ids) >= batch_size:
                    _delete_batch(gone_ids, public_schema)
                    total_deleted += len(gone_ids)
                    _bust_car_list_cache()
                    self.stdout.write(
                        self.style.SUCCESS(f"  ✓ Deleted {len(gone_ids)} cars.")
                    )
                    gone_ids = []

                # Progress every 100 cars
                if checked % 100 == 0:
                    elapsed = time.time() - t0
                    rate = checked / elapsed if elapsed else 0
                    self.stdout.write(f"  {checked}/{total} — {rate:.1f} cars/s")

        # Final flush
        if not dry_run and gone_ids:
            _delete_batch(gone_ids, public_schema)
            total_deleted += len(gone_ids)
            _bust_car_list_cache()
            self.stdout.write(
                self.style.SUCCESS(f"  ✓ Deleted {len(gone_ids)} cars (final).")
            )

        elapsed = time.time() - t0
        self.stdout.write(
            self.style.SUCCESS(
                f"\n=== Done in {elapsed:.0f}s === "
                f"checked={checked} "
                f"deleted={total_deleted if not dry_run else f'{len(gone_ids)} (dry-run)'} "
                f"unknown={unknown}"
            )
        )
