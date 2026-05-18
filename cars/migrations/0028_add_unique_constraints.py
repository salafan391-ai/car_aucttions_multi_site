"""
Add UniqueConstraint on Manufacturer(name) and CarModel(name, manufacturer).

Depends on 0027 having committed the dedup — that migration runs separately
so its FK-cascade DELETEs finalize before this ALTER TABLE runs.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cars", "0027_unique_manufacturer_carmodel"),
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
