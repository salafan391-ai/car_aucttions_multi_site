"""
Dedup duplicate Manufacturer / CarModel rows in-place, then lock the schema
with UniqueConstraints so the bug can't recur even if importer logic regresses.

Why: the auction importer historically created duplicate rows on every run
because its in-memory lookup dicts missed case-mismatched JSON values, and
`bulk_create(ignore_conflicts=True)` is a no-op without a unique index.

The dedup logic here matches `cars.management.commands.merge_brand_dupes`
Phase 1 + Phase 2: group by lower(name) for manufacturers and
(lower(name), manufacturer_id) for models, pick the lowest id as canonical,
repoint FK references (ApiCar, CarModel, CarBadge) and delete duplicates.
"""

from collections import defaultdict

from django.db import migrations, models


def _dedup_manufacturers_and_models(apps, schema_editor):
    Manufacturer = apps.get_model("cars", "Manufacturer")
    CarModel = apps.get_model("cars", "CarModel")
    CarBadge = apps.get_model("cars", "CarBadge")
    ApiCar = apps.get_model("cars", "ApiCar")

    def _norm(s):
        return (s or "").strip().lower()

    # ---- Phase 1: Manufacturer dedup ----
    clusters = defaultdict(list)
    for m in Manufacturer.objects.all().order_by("id"):
        clusters[_norm(m.name)].append(m)

    for key, rows in clusters.items():
        if len(rows) <= 1:
            continue
        rows.sort(key=lambda r: (_norm(r.name) != key, r.id))
        canonical = rows[0]
        for d in rows[1:]:
            ApiCar.objects.filter(manufacturer_id=d.id).update(manufacturer_id=canonical.id)
            CarModel.objects.filter(manufacturer_id=d.id).update(manufacturer_id=canonical.id)
            if d.name_ar and not canonical.name_ar:
                canonical.name_ar = d.name_ar
                canonical.save(update_fields=["name_ar"])
            Manufacturer.objects.filter(id=d.id).delete()
        # Promote canonical name to the normalized form so the constraint holds.
        if canonical.name != key:
            canonical.name = key
            canonical.save(update_fields=["name"])

    # Normalize remaining singleton rows too (some pre-existing rows may have
    # capital letters that haven't been re-saved since the constraint requires
    # equality on the exact stored value).
    for m in Manufacturer.objects.all():
        norm = _norm(m.name)
        if m.name != norm:
            Manufacturer.objects.filter(id=m.id).update(name=norm)

    # ---- Phase 2: CarModel dedup ----
    clusters = defaultdict(list)
    for m in CarModel.objects.all().order_by("id"):
        clusters[(_norm(m.name), m.manufacturer_id)].append(m)

    for (key_name, _mfr_id), rows in clusters.items():
        if len(rows) <= 1:
            continue
        rows.sort(key=lambda r: (_norm(r.name) != key_name, r.id))
        canonical = rows[0]
        for d in rows[1:]:
            ApiCar.objects.filter(model_id=d.id).update(model_id=canonical.id)
            CarBadge.objects.filter(model_id=d.id).update(model_id=canonical.id)
            if d.name_ar and not canonical.name_ar:
                canonical.name_ar = d.name_ar
                canonical.save(update_fields=["name_ar"])
            CarModel.objects.filter(id=d.id).delete()
        if canonical.name != key_name:
            canonical.name = key_name
            canonical.save(update_fields=["name"])

    # Normalize remaining singleton model rows.
    for m in CarModel.objects.all():
        norm = _norm(m.name)
        if m.name != norm:
            CarModel.objects.filter(id=m.id).update(name=norm)


def _noop_reverse(apps, schema_editor):
    # Dedup is destructive; reversing would not restore the deleted rows.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("cars", "0026_apicar_is_new"),
    ]

    operations = [
        migrations.RunPython(_dedup_manufacturers_and_models, _noop_reverse),
        migrations.AddConstraint(
            model_name="manufacturer",
            constraint=models.UniqueConstraint(
                fields=["name"],
                name="uniq_manufacturer_name",
            ),
        ),
        migrations.AddConstraint(
            model_name="carmodel",
            constraint=models.UniqueConstraint(
                fields=["name", "manufacturer"],
                name="uniq_carmodel_name_per_manufacturer",
            ),
        ),
    ]
