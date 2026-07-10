# The 0-accidents filter was seq-scanning and detoasting the large
# extra_features JSONB for every row (~3s per count on 180k cars) because the
# condition matches ~40% of the table, so the planner skipped the expression
# index. A STORED generated column keeps the tiny extracted value in the main
# heap — filters/counts never touch the TOASTed JSONB again, and Postgres
# maintains it automatically on insert/update.
#
# NOTE: adding a stored generated column rewrites the table (~1.5 GB), so this
# migration takes a minute or two on deploy.
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('cars', '0034_condition_filter_indexes')]
    operations = [
        migrations.RunSQL(
            sql=[
                # the app's connections carry a 30s statement_timeout — far too
                # short for the table rewrite; lift it for this transaction only
                "SET LOCAL statement_timeout = 0;",
                "ALTER TABLE cars_apicar ADD COLUMN IF NOT EXISTS accident_cnt text "
                "GENERATED ALWAYS AS ((extra_features -> 'record' ->> 'accidentCnt')) STORED;",
                # replace the old expression index with one on the real column
                "DROP INDEX IF EXISTS cars_apicar_accident_cnt;",
                "CREATE INDEX IF NOT EXISTS cars_apicar_accident_cnt ON cars_apicar (accident_cnt);",
                "ANALYZE cars_apicar;",
            ],
            reverse_sql=[
                "DROP INDEX IF EXISTS cars_apicar_accident_cnt;",
                "ALTER TABLE cars_apicar DROP COLUMN IF EXISTS accident_cnt;",
                "CREATE INDEX IF NOT EXISTS cars_apicar_accident_cnt ON cars_apicar "
                "(((extra_features -> 'record' ->> 'accidentCnt')));",
            ],
        ),
    ]
