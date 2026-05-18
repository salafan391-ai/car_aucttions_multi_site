"""
Add UniqueConstraint on Manufacturer(name) and CarModel(name, manufacturer).

Why: the auction importer historically created duplicate rows on every run
because its in-memory lookup dicts missed case-mismatched JSON values, and
`bulk_create(ignore_conflicts=True)` is a no-op without a unique index.
After the merge_brand_dupes cleanup the table is dedup'd; this constraint
locks it in so the bug can't recur even if importer logic regresses.

Run `python manage.py merge_brand_dupes --apply` BEFORE applying this
migration — otherwise it will fail on remaining duplicate rows.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cars", "0026_apicar_is_new"),
    ]

    operations = [
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
