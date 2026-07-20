"""Collapse detailed gearbox strings to the standard types.

Japanese listings arrive as "6at w/ manual mode (floor shift)", "cvt (column
shift)", "5mt (floor shift)" — 64 distinct values, which makes the transmission
filter unusable and leaves everything untranslated. normalize_transmission now
maps these, so this command brings existing rows in line.
"""
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.models import Count

from cars.models import ApiCar
from cars.normalization import normalize_transmission


class Command(BaseCommand):
    help = "Rewrite detailed transmission values to automatic / manual / cvt."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        rows = (ApiCar.objects.exclude(transmission__isnull=True).exclude(transmission="")
                .values("transmission").annotate(c=Count("id")).order_by("-c"))

        plan = {}
        for r in rows:
            src = r["transmission"]
            dst = normalize_transmission(src)
            if dst and dst != src:
                plan.setdefault(dst, []).append((src, r["c"]))

        if not plan:
            self.stdout.write(self.style.SUCCESS("Nothing to change."))
            return

        total = 0
        for dst, srcs in sorted(plan.items()):
            n = sum(c for _, c in srcs)
            total += n
            self.stdout.write(f"  -> {dst}: {len(srcs)} value(s), {n:,} cars")
            for src, c in sorted(srcs, key=lambda x: -x[1])[:3]:
                self.stdout.write(f"       {src}  ({c:,})")

        if dry:
            self.stdout.write(self.style.SUCCESS(
                f"\nDry run — {total:,} cars across {sum(len(v) for v in plan.values())} "
                f"values would be rewritten."))
            return

        # Maintenance run: the 25s web timeout would kill a 500k-row update.
        with connection.cursor() as cur:
            cur.execute("SET statement_timeout = '900s'")
        done = 0
        for dst, srcs in plan.items():
            names = [s for s, _ in srcs]
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(
                    "UPDATE cars_apicar SET transmission = %s WHERE transmission = ANY(%s)",
                    [dst, names])
                done += cur.rowcount
        self.stdout.write(self.style.SUCCESS(f"\nRewrote {done:,} cars."))
