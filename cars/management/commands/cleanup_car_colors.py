from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.models import Count

from cars.models import ApiCar, CarColor, CarSeatColor

# Junk placeholders the feed uses instead of a real colour — folded into one
# bucket so the filter shows a single "غير محدد" option instead of three.
ALIASES = {'etc': 'unknown', 'others': 'unknown'}

TARGETS = ((CarColor, 'color'), (CarSeatColor, 'seat_color'))


def _key(name):
    k = (name or '').strip().lower()
    return ALIASES.get(k, k)


class Command(BaseCommand):
    help = ("Merge duplicate colour rows (same name stored several times) and "
            "delete colour rows no car references. Shared catalogue data, so "
            "run --dry-run first.")

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--no-purge', action='store_true',
                            help='merge duplicates but keep unreferenced rows')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        if not dry:
            # Maintenance run, not a web request: the 25s web timeout would kill
            # the bulk update/delete partway through.
            with connection.cursor() as cur:
                cur.execute("SET statement_timeout = '900s'")
        for Model, field in TARGETS:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n{Model.__name__} (ApiCar.{field})"))
            merged, moved = self._merge(Model, field, dry)
            purged = 0 if opts['no_purge'] else self._purge(Model, field, dry)
            verb = "would merge" if dry else "merged"
            self.stdout.write(
                f"  {verb} {merged} duplicate rows ({moved} cars repointed), "
                f"{'would purge' if dry else 'purged'} {purged} unused rows")
        self.stdout.write(self.style.SUCCESS(
            "\nDry run — nothing written." if dry else "\nDone."))

    def _usage(self, field):
        return dict(ApiCar.objects
                    .exclude(**{f'{field}__isnull': True})
                    .values(f'{field}_id')
                    .annotate(c=Count('id'))
                    .values_list(f'{field}_id', 'c'))

    def _merge(self, Model, field, dry):
        usage = self._usage(field)
        groups = defaultdict(list)
        for pk, name in Model.objects.values_list('id', 'name'):
            groups[_key(name)].append(pk)

        merged = moved = 0
        for key, ids in sorted(groups.items()):
            if len(ids) < 2:
                continue
            # Keep the most-used row; ties go to the lowest id.
            canonical = max(ids, key=lambda i: (usage.get(i, 0), -i))
            others = [i for i in ids if i != canonical]
            n_cars = sum(usage.get(i, 0) for i in others)
            self.stdout.write(
                f"    {key!r}: keep #{canonical} ({usage.get(canonical, 0)} cars), "
                f"merge {others} (+{n_cars} cars)")
            if not dry:
                with transaction.atomic(), connection.cursor() as cur:
                    cur.execute(
                        f"UPDATE cars_apicar SET {field}_id = %s "
                        f"WHERE {field}_id = ANY(%s)", [canonical, others])
                    cur.execute(
                        f"DELETE FROM {Model._meta.db_table} WHERE id = ANY(%s)",
                        [others])
            merged += len(others)
            moved += n_cars
        return merged, moved

    def _purge(self, Model, field, dry):
        """Delete rows nothing points at (checked fresh, after the merge)."""
        used = set(self._usage(field))
        dead = list(Model.objects.exclude(id__in=used).values_list('id', flat=True))
        if not dead:
            return 0
        if dry:
            return len(dead)
        # Delete in chunks: one 17k-row statement stalls, and the ORM's cascade
        # collector would load every related row first. A referenced id would
        # raise a ForeignKeyViolation, so the constraint guards correctness.
        done = 0
        for i in range(0, len(dead), 2000):
            chunk = dead[i:i + 2000]
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {Model._meta.db_table} WHERE id = ANY(%s)", [chunk])
            done += len(chunk)
        return done
