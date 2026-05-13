"""
Merge duplicate Manufacturer / CarModel / CarBadge rows.

Why: production accumulated duplicates because there are no unique constraints
on these tables, `bulk_create(ignore_conflicts=True)` is a no-op without a
unique index, and the importer's in-memory `new_models` dict was keyed by
model_name alone (so the same name under different manufacturers, or repeated
across import batches, kept inserting new rows). Some Arabic-only Manufacturer
rows also slipped in alongside their English counterparts, causing FK divergence.

Usage:
    python manage.py merge_brand_dupes --tenant=<schema>            # dry-run
    python manage.py merge_brand_dupes --tenant=<schema> --apply    # commit

By default only manufacturers + models are merged. Pass --badges to also dedup
CarBadge rows (skipped by default because badges can legitimately repeat across
models, and we group strictly by (name, model_id) which is safe but slower).
"""

from collections import defaultdict
import re

from django.core.management.base import BaseCommand
from django.db import transaction
from django_tenants.utils import schema_context

from cars.models import ApiCar, CarBadge, CarModel, Manufacturer


_ARABIC_RE = re.compile(r'[؀-ۿ]')


def _is_arabic(name):
    return bool(name) and bool(_ARABIC_RE.search(name))


def _norm(name):
    return (name or '').strip().lower()


class Command(BaseCommand):
    help = "Merge duplicate Manufacturer / CarModel / CarBadge rows in a tenant schema."

    def add_arguments(self, parser):
        parser.add_argument('--tenant', default='public', help='Tenant schema (cars is a SHARED_APP so public is the right place; default: public).')
        parser.add_argument('--apply', action='store_true', help='Actually write changes. Default is dry-run.')
        parser.add_argument('--badges', action='store_true', help='Also dedup CarBadge rows.')
        parser.add_argument(
            '--arabic-pair', action='append', default=[],
            metavar='AR=EN',
            help="Force an Arabic Manufacturer name to merge into an English one. Repeatable, "
                 "e.g. --arabic-pair جينسس=genesis --arabic-pair لكسز=lexus",
        )
        parser.add_argument(
            '--rename-pair', action='append', default=[],
            metavar='OLD=NEW',
            help="Force a Manufacturer name (English or anything) to merge into another. "
                 "Use when two English variants exist for one brand. Repeatable, e.g. "
                 "--rename-pair 'kgm=ssangyong' --rename-pair 'benz=mercedes-benz'",
        )

    def handle(self, *args, **options):
        schema = options['tenant']
        apply_changes = options['apply']
        do_badges = options['badges']

        # Parse both --arabic-pair AR=EN and --rename-pair OLD=NEW into a single
        # case-insensitive {from_lower: to_lower} map; both flags do the same job
        # (rename source name → canonical name), kept separate only for readability.
        forced_pairs = {}
        for flag, raw_values in (('--arabic-pair', options['arabic_pair']),
                                 ('--rename-pair', options['rename_pair'])):
            for raw in raw_values:
                if '=' not in raw:
                    self.stderr.write(self.style.ERROR(f"  bad {flag} value (missing '='): {raw!r}"))
                    continue
                src, dst = raw.split('=', 1)
                forced_pairs[src.strip().lower()] = dst.strip().lower()

        mode = self.style.SUCCESS('APPLY') if apply_changes else self.style.WARNING('DRY-RUN')
        self.stdout.write(f"\n=== merge_brand_dupes — schema={schema} mode={mode} ===\n")

        with schema_context(schema):
            if apply_changes:
                with transaction.atomic():
                    self._run(apply_changes, do_badges, forced_pairs)
            else:
                self._run(apply_changes, do_badges, forced_pairs)

    def _run(self, apply_changes, do_badges, forced_pairs):
        # ---- Phase 1: Manufacturer dedup ----
        self.stdout.write(self.style.MIGRATE_HEADING("\nPhase 1: Manufacturer dedup"))
        canonical_by_id = self._merge_manufacturers(apply_changes, forced_pairs)

        # ---- Phase 2: CarModel dedup ----
        self.stdout.write(self.style.MIGRATE_HEADING("\nPhase 2: CarModel dedup"))
        self._merge_car_models(apply_changes, canonical_by_id)

        # ---- Phase 3: CarBadge dedup (optional) ----
        if do_badges:
            self.stdout.write(self.style.MIGRATE_HEADING("\nPhase 3: CarBadge dedup"))
            self._merge_car_badges(apply_changes)
        else:
            self.stdout.write("\n(skip CarBadge dedup — pass --badges to enable)")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("\nDry-run complete. Re-run with --apply to commit."))

    # ---------------------------------------------------------------
    # Phase 1 — Manufacturer
    # ---------------------------------------------------------------
    def _merge_manufacturers(self, apply_changes, forced_pairs):
        """
        Returns a mapping {old_manufacturer_id: canonical_manufacturer_id} covering
        only IDs that changed (canonical IDs map to themselves implicitly).
        Used by Phase 2 to remap CarModel.manufacturer_id before regrouping models.
        """
        all_mfrs = list(Manufacturer.objects.all().order_by('id'))
        self.stdout.write(f"  total Manufacturer rows: {len(all_mfrs)}")

        # Partition: forced_pairs gets first crack at rewriting each row's name
        # (handles English↔English brand variants AND Arabic→English). Rows that
        # remain Arabic after rewrite are deferred to the name_ar auto-pair step.
        english_clusters = defaultdict(list)
        arabic_rows = []
        for m in all_mfrs:
            raw_lower = _norm(m.name)
            effective = forced_pairs.get(raw_lower, raw_lower)
            if _is_arabic(effective):
                arabic_rows.append(m)
            else:
                english_clusters[effective].append(m)

        # Pair leftover Arabic-only rows by matching their name against an
        # English canonical row's name_ar.
        ar_to_en = {}
        for key, rows in english_clusters.items():
            for r in rows:
                if r.name_ar:
                    ar_to_en.setdefault(r.name_ar.strip(), key)

        unmatched_arabic = []
        for m in arabic_rows:
            en_key = ar_to_en.get((m.name or '').strip())
            if en_key and en_key in english_clusters:
                english_clusters[en_key].append(m)
            else:
                unmatched_arabic.append(m)

        # Report unmatched Arabic rows — they need a human decision.
        if unmatched_arabic:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ {len(unmatched_arabic)} Arabic-only Manufacturer rows have no English match; leaving alone:"
            ))
            for m in unmatched_arabic:
                car_count = ApiCar.objects.filter(manufacturer_id=m.id).count()
                self.stdout.write(f"      id={m.id} name={m.name!r} cars={car_count}")

        # Process clusters with >1 row.
        remap = {}
        total_merged = 0
        cars_repointed = 0
        models_repointed = 0
        for key, rows in english_clusters.items():
            if len(rows) <= 1:
                continue
            # Prefer the row already named like the cluster key — when forced_pairs
            # rewrote some rows into this cluster, this keeps the canonical's label
            # readable (e.g. avoids picking 'renault samsung' as canonical for the
            # renault cluster just because its id is lowest).
            rows.sort(key=lambda r: (_norm(r.name) != key, r.id))
            canonical = rows[0]
            dupes = rows[1:]
            self.stdout.write(f"  cluster {key!r}: canonical id={canonical.id} (name={canonical.name!r}) ← {len(dupes)} dupes")
            for d in dupes:
                car_cnt = ApiCar.objects.filter(manufacturer_id=d.id).count()
                mod_cnt = CarModel.objects.filter(manufacturer_id=d.id).count()
                self.stdout.write(f"      drop id={d.id} name={d.name!r} cars={car_cnt} models={mod_cnt}")
                remap[d.id] = canonical.id
                cars_repointed += car_cnt
                models_repointed += mod_cnt
                total_merged += 1

                if apply_changes:
                    ApiCar.objects.filter(manufacturer_id=d.id).update(manufacturer_id=canonical.id)
                    CarModel.objects.filter(manufacturer_id=d.id).update(manufacturer_id=canonical.id)
                    # Promote name_ar to canonical if it's missing there.
                    if d.name_ar and not canonical.name_ar:
                        canonical.name_ar = d.name_ar
                        canonical.save(update_fields=['name_ar'])
                    Manufacturer.objects.filter(id=d.id).delete()

        self.stdout.write(
            f"  → {total_merged} duplicate manufacturers merged; "
            f"{cars_repointed} cars + {models_repointed} models repointed"
        )
        return remap

    # ---------------------------------------------------------------
    # Phase 2 — CarModel
    # ---------------------------------------------------------------
    def _merge_car_models(self, apply_changes, mfr_remap):
        """
        Group CarModel by (lower(name), manufacturer_id) after Phase 1 already
        collapsed the manufacturer side. For each cluster of >1, pick lowest id
        and repoint ApiCar.model_id + CarBadge.model_id, then delete dupes.
        """
        all_models = list(CarModel.objects.all().order_by('id'))
        self.stdout.write(f"  total CarModel rows: {len(all_models)}")

        clusters = defaultdict(list)
        for m in all_models:
            # mfr_remap is only populated when --apply ran Phase 1; in dry-run,
            # also virtually-repoint so the cluster count reflects post-merge state.
            mfr_id = mfr_remap.get(m.manufacturer_id, m.manufacturer_id)
            clusters[(_norm(m.name), mfr_id)].append(m)

        total_merged = 0
        cars_repointed = 0
        badges_repointed = 0
        for (name_key, mfr_id), rows in clusters.items():
            if len(rows) <= 1:
                continue
            rows.sort(key=lambda r: r.id)
            canonical = rows[0]
            dupes = rows[1:]
            self.stdout.write(
                f"  cluster name={name_key!r} mfr_id={mfr_id}: canonical id={canonical.id} ← {len(dupes)} dupes"
            )
            for d in dupes:
                car_cnt = ApiCar.objects.filter(model_id=d.id).count()
                bdg_cnt = CarBadge.objects.filter(model_id=d.id).count()
                self.stdout.write(f"      drop id={d.id} cars={car_cnt} badges={bdg_cnt}")
                cars_repointed += car_cnt
                badges_repointed += bdg_cnt
                total_merged += 1

                if apply_changes:
                    ApiCar.objects.filter(model_id=d.id).update(model_id=canonical.id)
                    CarBadge.objects.filter(model_id=d.id).update(model_id=canonical.id)
                    if d.name_ar and not canonical.name_ar:
                        canonical.name_ar = d.name_ar
                        canonical.save(update_fields=['name_ar'])
                    CarModel.objects.filter(id=d.id).delete()

        self.stdout.write(
            f"  → {total_merged} duplicate models merged; "
            f"{cars_repointed} cars + {badges_repointed} badges repointed"
        )

    # ---------------------------------------------------------------
    # Phase 3 — CarBadge (optional)
    # ---------------------------------------------------------------
    def _merge_car_badges(self, apply_changes):
        all_badges = list(CarBadge.objects.all().order_by('id'))
        self.stdout.write(f"  total CarBadge rows: {len(all_badges)}")

        clusters = defaultdict(list)
        for b in all_badges:
            clusters[(_norm(b.name), b.model_id)].append(b)

        total_merged = 0
        cars_repointed = 0
        for (name_key, model_id), rows in clusters.items():
            if len(rows) <= 1:
                continue
            rows.sort(key=lambda r: r.id)
            canonical = rows[0]
            dupes = rows[1:]
            self.stdout.write(
                f"  cluster name={name_key!r} model_id={model_id}: canonical id={canonical.id} ← {len(dupes)} dupes"
            )
            for d in dupes:
                car_cnt = ApiCar.objects.filter(badge_id=d.id).count()
                self.stdout.write(f"      drop id={d.id} cars={car_cnt}")
                cars_repointed += car_cnt
                total_merged += 1

                if apply_changes:
                    ApiCar.objects.filter(badge_id=d.id).update(badge_id=canonical.id)
                    CarBadge.objects.filter(id=d.id).delete()

        self.stdout.write(f"  → {total_merged} duplicate badges merged; {cars_repointed} cars repointed")
