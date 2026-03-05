# Generated manually on 2026-03-05

from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Add covering indexes for the static filter sidebar queries.

    These queries all follow the pattern:
        SELECT DISTINCT <field> FROM cars_apicar
        LEFT JOIN cars_category ON ...
        WHERE NOT (auction_date < now AND category = 'auction')
        ORDER BY <field>

    By adding composite indexes on (category_id, <field>), PostgreSQL can
    satisfy both the WHERE predicate and the DISTINCT/ORDER BY from the index
    alone — turning full sequential scans into fast index-only scans.

    Index inventory:
      cars_apicar_cat_fuel_idx       — fuel filter dropdown
      cars_apicar_cat_transmission_idx — transmission filter dropdown
      cars_apicar_cat_seat_count_idx  — seat count filter dropdown
      cars_apicar_cat_body_idx        — body type filter (covers body_id subquery)
      cars_apicar_cat_color_idx       — color filter (covers color_id subquery)
      cars_apicar_cat_seat_color_idx  — seat color filter
      cars_apicar_cat_year_idx        — year range filter + DISTINCT years list
    """

    dependencies = [
        ("cars", "0016_add_category_auction_date_covering_index"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="apicar",
            index=models.Index(
                fields=["category", "fuel"],
                name="cars_apicar_cat_fuel_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="apicar",
            index=models.Index(
                fields=["category", "transmission"],
                name="cars_apicar_cat_trans_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="apicar",
            index=models.Index(
                fields=["category", "seat_count"],
                name="cars_apicar_cat_seat_cnt_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="apicar",
            index=models.Index(
                fields=["category", "body"],
                name="cars_apicar_cat_body_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="apicar",
            index=models.Index(
                fields=["category", "color"],
                name="cars_apicar_cat_color_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="apicar",
            index=models.Index(
                fields=["category", "seat_color"],
                name="cars_apicar_cat_seat_clr_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="apicar",
            index=models.Index(
                fields=["category", "-year"],
                name="cars_apicar_cat_year_idx",
            ),
        ),
    ]
