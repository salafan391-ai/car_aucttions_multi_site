from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
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
        for Model, field in TARGETS:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n{Model.__name__} (ApiCar.{field})"))
            with transaction.atomic():
                merged, moved = self._merge(Model, field, dry)
                purged = 0 if opts['no_purge'] else self._purge(Model, field, dry)
                if dry:
                    transaction.set_rollback(True)
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
                ApiCar.objects.filter(**{f'{field}_id__in': others}).update(
                    **{f'{field}_id': canonical})
                Model.objects.filter(id__in=others).delete()
            merged += len(others)
            moved += n_cars
        return merged, moved

    def _purge(self, Model, field, dry):
        """Delete rows nothing points at (checked fresh, after the merge)."""
        used = set(self._usage(field))
        dead = list(Model.objects.exclude(id__in=used).values_list('id', flat=True))
        if not dead:
            return 0
        if not dry:
            # Re-check under the same transaction before deleting.
            still = set(ApiCar.objects.filter(**{f'{field}_id__in': dead})
                        .values_list(f'{field}_id', flat=True))
            safe = [i for i in dead if i not in still]
            Model.objects.filter(id__in=safe).delete()
            return len(safe)
        return len(dead)
