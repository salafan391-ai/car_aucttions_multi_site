"""Backfill the Encar "grade base" price (category.originPrice, in 만원) into
``ApiCar.extra_features['originPrice']`` so the detail page can show the
new-car-vs-current price comparison (신차대비).

originPrice is not in the import feed; we read it from Encar's public read API
``https://api.encar.com/v1/readside/vehicle/<vehicleId>`` using the vehicleId
already stored in extra_features. Idempotent: cars that already have
``originPrice`` are skipped, so it is safe to re-run / resume.

Usage:
    DATABASE_URL=<public> python manage.py backfill_origin_price --limit 200
    python manage.py backfill_origin_price --ids 590624 --force
    python manage.py backfill_origin_price --only-available --sleep 0.3
"""

from __future__ import annotations

import time

import requests
from django.core.management.base import BaseCommand

from cars.models import ApiCar

API = "https://api.encar.com/v1/readside/vehicle/{}"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class Command(BaseCommand):
    help = "Backfill extra_features['originPrice'] (만원) from the Encar read API."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None,
                            help="Process at most N cars.")
        parser.add_argument("--ids", default="",
                            help="Comma-separated ApiCar pks to backfill (ignores other filters).")
        parser.add_argument("--only-available", action="store_true",
                            help="Only cars with status='available'.")
        parser.add_argument("--sleep", type=float, default=0.25,
                            help="Seconds to sleep between API calls (rate limit).")
        parser.add_argument("--force", action="store_true",
                            help="Re-fetch even if originPrice already present.")

    def handle(self, *args, **opts):
        qs = ApiCar.objects.exclude(extra_features__isnull=True)
        if opts["ids"]:
            pks = [int(x) for x in opts["ids"].split(",") if x.strip()]
            qs = ApiCar.objects.filter(pk__in=pks)
        else:
            qs = qs.filter(extra_features__has_key="vehicleId")
            if not opts["force"]:
                qs = qs.exclude(extra_features__has_key="originPrice")
            if opts["only_available"]:
                qs = qs.filter(status="available")
        qs = qs.only("id", "extra_features")
        if opts["limit"]:
            qs = qs[: opts["limit"]]

        sess = requests.Session()
        sess.headers.update({"User-Agent": UA, "Referer": "https://fem.encar.com/",
                             "Accept": "application/json"})

        done = updated = missing = errors = 0
        batch = []
        for car in qs.iterator(chunk_size=500):
            ef = car.extra_features or {}
            vid = ef.get("vehicleId")
            if not vid:
                continue
            done += 1
            try:
                r = sess.get(API.format(vid), timeout=20)
                if r.status_code != 200:
                    missing += 1
                else:
                    op = (r.json().get("category") or {}).get("originPrice")
                    if op:
                        ef["originPrice"] = int(op)
                        car.extra_features = ef
                        batch.append(car)
                        updated += 1
                    else:
                        missing += 1
            except (requests.RequestException, ValueError):
                errors += 1
            if len(batch) >= 200:
                ApiCar.objects.bulk_update(batch, ["extra_features"])
                batch.clear()
            if done % 200 == 0:
                self.stdout.write(f"  …{done} checked, {updated} updated, "
                                  f"{missing} no-data, {errors} errors")
            if opts["sleep"]:
                time.sleep(opts["sleep"])

        if batch:
            ApiCar.objects.bulk_update(batch, ["extra_features"])

        self.stdout.write(self.style.SUCCESS(
            f"Done. checked={done} updated={updated} no-data={missing} errors={errors}"
        ))
