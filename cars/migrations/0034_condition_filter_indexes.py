from django.db import migrations


# Speed up the "car condition" filters (clean_main / no_accident):
#
# 1. `extra_features` is the full Encar payload (a large TOASTed JSONB), so
#    filtering on record.accidentCnt detoasts ~167k blobs per query (~5s).
#    A btree expression index on the extracted text value makes the
#    `->> = '0'` comparison an index lookup. The query side must use the
#    exact same expression (see _NO_ACCIDENT_WHERE in cars/views.py).
#
# 2. Only auction cars carry `markers`; a partial index lets the
#    damaged-main-parts subquery visit just those ~9k rows instead of
#    seq-scanning the whole table.
ACCIDENT_IDX = (
    "CREATE INDEX IF NOT EXISTS cars_apicar_accident_cnt "
    "ON cars_apicar (((extra_features -> 'record' ->> 'accidentCnt')));"
)
MARKERS_IDX = (
    "CREATE INDEX IF NOT EXISTS cars_apicar_has_markers "
    "ON cars_apicar (id) WHERE markers IS NOT NULL;"
)


class Migration(migrations.Migration):

    dependencies = [("cars", "0033_car_dmg_types_fn")]

    operations = [
        migrations.RunSQL(ACCIDENT_IDX, reverse_sql="DROP INDEX IF EXISTS cars_apicar_accident_cnt;"),
        migrations.RunSQL(MARKERS_IDX, reverse_sql="DROP INDEX IF EXISTS cars_apicar_has_markers;"),
    ]
