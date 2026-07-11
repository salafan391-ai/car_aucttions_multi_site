# The 0-accidents filter now also excludes cars with exchanged (X-coded)
# panels from the Encar inspection sheet / auction markers. car_dmg_types is
# too heavy to evaluate per row at query time (detoasts extra_features), so
# the verdict is materialized as a STORED generated column, like accident_cnt
# (migration 0035). Applied out-of-band via psql on prod (table rewrite);
# IF NOT EXISTS makes this a fast no-op there and self-sufficient elsewhere.
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('cars', '0035_accident_cnt_generated_column')]
    operations = [
        migrations.RunSQL(
            sql=[
                "SET LOCAL statement_timeout = 0;",
                "ALTER TABLE cars_apicar ADD COLUMN IF NOT EXISTS dmg_replaced boolean "
                "GENERATED ALWAYS AS (car_dmg_types(extra_features, markers) @> ARRAY['replaced']::text[]) STORED;",
                "CREATE INDEX IF NOT EXISTS cars_apicar_dmg_replaced ON cars_apicar (dmg_replaced);",
                "ANALYZE cars_apicar;",
            ],
            reverse_sql=[
                "DROP INDEX IF EXISTS cars_apicar_dmg_replaced;",
                "ALTER TABLE cars_apicar DROP COLUMN IF EXISTS dmg_replaced;",
            ],
        ),
    ]
