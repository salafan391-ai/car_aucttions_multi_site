"""Delete manufacturer rows whose name is mojibake (double-encoded import junk).

These clutter the admin catalogue filter, which lists every manufacturer.
Only rows referenced by zero cars are removed — ApiCar.manufacturer cascades,
so a row still in use must never be deleted.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from cars.models import ApiCar, Manufacturer


def is_corrupt(name):
    """Mojibake mixes Cyrillic/Greek/box-drawing (or Arabic+symbols) into what
    should be Latin/CJK/Hangul text — a combination no real make name has."""
    if not name:
        return False
    blocks = set()
    for ch in name:
        cp = ord(ch)
        # Latin Extended-A/B and typographic quotes never occur in a real make
        # name, but are the signature of Mac-Roman/CP1252 double-encoding.
        # NB: Latin-1 accents (é, ë in "citroën") are 0x00C0-0x00FF — allowed.
        if 0x0100 <= cp <= 0x024F or 0x2018 <= cp <= 0x201F:
            return True
        if 0x0400 <= cp <= 0x04FF:
            blocks.add("cyrillic")
        elif 0x0370 <= cp <= 0x03FF:
            blocks.add("greek")
        elif 0x2500 <= cp <= 0x257F:
            blocks.add("box")
        elif 0x0600 <= cp <= 0x06FF:
            blocks.add("arabic")
        elif 0x2010 <= cp <= 0x2BFF:
            blocks.add("symbol")
    return bool(blocks & {"cyrillic", "greek", "box"}) or (
        "arabic" in blocks and "symbol" in blocks)


class Command(BaseCommand):
    help = "Remove manufacturers with corrupted (mojibake) names that no car uses."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        used = dict(ApiCar.objects.values("manufacturer_id")
                    .annotate(c=Count("id")).values_list("manufacturer_id", "c"))

        corrupt, skipped = [], []
        for pk, name in Manufacturer.objects.values_list("id", "name"):
            if not is_corrupt(name):
                continue
            (skipped if used.get(pk, 0) else corrupt).append((pk, name, used.get(pk, 0)))

        for pk, name, _ in corrupt[:10]:
            self.stdout.write(f"    {'would delete' if dry else 'deleting'} #{pk} {name!r}")
        if len(corrupt) > 10:
            self.stdout.write(f"    ... and {len(corrupt) - 10} more")

        if skipped:
            self.stdout.write(self.style.WARNING(
                f"  KEPT {len(skipped)} corrupted row(s) that still have cars "
                f"(deleting them would cascade-delete listings): "
                + ", ".join(f"#{p}({c} cars)" for p, _, c in skipped[:5])))

        if not dry and corrupt:
            ids = [p for p, _, _ in corrupt]
            with transaction.atomic():
                # Re-check under the transaction; never cascade into real cars.
                still = set(ApiCar.objects.filter(manufacturer_id__in=ids)
                            .values_list("manufacturer_id", flat=True))
                safe = [i for i in ids if i not in still]
                Manufacturer.objects.filter(id__in=safe).delete()
            self.stdout.write(self.style.SUCCESS(f"\nDeleted {len(safe)} rows."))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\nDry run — {len(corrupt)} row(s) would be deleted."
                if dry else "\nNothing to delete."))
