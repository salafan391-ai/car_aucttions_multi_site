"""
Normalize car data across tenant schemas:

  - Lowercase Manufacturer/CarModel/CarBadge/CarColor/BodyType names
    and merge duplicates created by the case collapse (reassigning FKs).
  - Canonicalize synonyms (e.g. 'Pickup Truck' -> 'truck',
    'أوتوماتيك' -> 'automatic').
  - Lowercase ApiCar.fuel and ApiCar.transmission values.

Use --dry-run (default) to preview changes; pass --apply to commit.
Optionally limit to one tenant with --schema <schema_name>.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django_tenants.utils import schema_context, get_tenant_model

from cars.normalization import (
    BODY_SYNONYMS, TRANSMISSION_SYNONYMS, FUEL_SYNONYMS,
    normalize_name as _norm,
)


class Command(BaseCommand):
    help = "Normalize car data (lowercase names, merge duplicates, canonicalize synonyms)."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Apply changes (default is dry-run).')
        parser.add_argument('--schema', type=str, default=None,
                            help='Only run against this tenant schema.')

    def handle(self, *args, **options):
        apply_changes = options['apply']
        only_schema = options['schema']

        TenantModel = get_tenant_model()
        tenants = TenantModel.objects.exclude(schema_name='public')
        if only_schema:
            tenants = tenants.filter(schema_name=only_schema)

        for tenant in tenants:
            self.stdout.write(self.style.NOTICE(f'\n===== schema={tenant.schema_name} ====='))
            with schema_context(tenant.schema_name):
                if apply_changes:
                    with transaction.atomic():
                        self._process(apply_changes=True)
                else:
                    self._process(apply_changes=False)

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                '\nDry run complete. Re-run with --apply to commit changes.'
            ))

    def _process(self, apply_changes):
        from cars.models import (
            ApiCar, Manufacturer, CarModel, CarBadge, CarColor, BodyType,
        )

        # --- Lookup tables: lowercase + merge duplicates ---
        self._normalize_lookup(
            Model=Manufacturer,
            fk_updates=[(ApiCar, 'manufacturer_id'), (CarModel, 'manufacturer_id')],
            scope_field=None,
            synonyms=None,
            preserve_fields=('name_ar', 'country', 'logo'),
            apply_changes=apply_changes,
        )
        self._normalize_lookup(
            Model=CarModel,
            fk_updates=[(ApiCar, 'model_id'), (CarBadge, 'model_id')],
            scope_field='manufacturer_id',
            synonyms=None,
            preserve_fields=('name_ar',),
            apply_changes=apply_changes,
        )
        self._normalize_lookup(
            Model=CarBadge,
            fk_updates=[(ApiCar, 'badge_id')],
            scope_field='model_id',
            synonyms=None,
            preserve_fields=(),
            apply_changes=apply_changes,
        )
        self._normalize_lookup(
            Model=CarColor,
            fk_updates=[(ApiCar, 'color_id')],
            scope_field=None,
            synonyms=None,
            preserve_fields=(),
            apply_changes=apply_changes,
        )
        self._normalize_lookup(
            Model=BodyType,
            fk_updates=[(ApiCar, 'body_id')],
            scope_field=None,
            synonyms=BODY_SYNONYMS,
            preserve_fields=('name_ar',),
            apply_changes=apply_changes,
        )

        # --- ApiCar plain-text columns: fuel + transmission ---
        self._normalize_plain_column(
            column='fuel', synonyms=FUEL_SYNONYMS,
            apply_changes=apply_changes,
        )
        self._normalize_plain_column(
            column='transmission', synonyms=TRANSMISSION_SYNONYMS,
            apply_changes=apply_changes,
        )

    def _normalize_lookup(self, Model, fk_updates, scope_field, synonyms,
                          preserve_fields, apply_changes):
        label = Model.__name__
        groups = {}
        for obj in Model.objects.all():
            norm = _norm(obj.name, synonyms)
            scope_val = getattr(obj, scope_field) if scope_field else None
            groups.setdefault((scope_val, norm), []).append(obj)

        rename_count = 0
        merge_count = 0
        for (_, norm_name), group in groups.items():
            if norm_name is None:
                continue
            # Choose canonical = lowest id
            group.sort(key=lambda o: o.id)
            canonical = group[0]
            duplicates = group[1:]

            # Merge duplicates into canonical
            for dup in duplicates:
                merge_count += 1
                self.stdout.write(
                    f'  [{label}] merge id={dup.id} name={dup.name!r} '
                    f'-> id={canonical.id} name={canonical.name!r} (norm={norm_name!r})'
                )
                if apply_changes:
                    # Preserve non-null auxiliary fields if canonical lacks them
                    changed_canon_fields = []
                    for fld in preserve_fields:
                        if not getattr(canonical, fld, None) and getattr(dup, fld, None):
                            setattr(canonical, fld, getattr(dup, fld))
                            changed_canon_fields.append(fld)
                    if changed_canon_fields:
                        canonical.save(update_fields=changed_canon_fields)

                    for fk_model, fk_field in fk_updates:
                        fk_model.objects.filter(**{fk_field: dup.id}).update(**{fk_field: canonical.id})
                    dup.delete()

            # Rename canonical if needed
            if canonical.name != norm_name:
                rename_count += 1
                self.stdout.write(
                    f'  [{label}] rename id={canonical.id} {canonical.name!r} -> {norm_name!r}'
                )
                if apply_changes:
                    canonical.name = norm_name
                    canonical.save(update_fields=['name'])

        self.stdout.write(self.style.SUCCESS(
            f'  [{label}] renamed={rename_count}  merged={merge_count}'
        ))

    def _normalize_plain_column(self, column, synonyms, apply_changes):
        from cars.models import ApiCar
        label = f'ApiCar.{column}'
        distinct = list(
            ApiCar.objects.values_list(column, flat=True).distinct()
        )
        updates = []
        for v in distinct:
            if v is None:
                continue
            new_v = _norm(v, synonyms)
            if new_v != v:
                updates.append((v, new_v))

        total_rows_changed = 0
        for old, new in updates:
            count = ApiCar.objects.filter(**{column: old}).count()
            total_rows_changed += count
            self.stdout.write(
                f'  [{label}] {old!r} -> {new!r}  ({count} rows)'
            )
            if apply_changes:
                ApiCar.objects.filter(**{column: old}).update(**{column: new})

        self.stdout.write(self.style.SUCCESS(
            f'  [{label}] distinct updates={len(updates)}  rows changed={total_rows_changed}'
        ))
