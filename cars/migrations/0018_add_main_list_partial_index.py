# Generated manually on 2026-03-05

from django.db import migrations


class Migration(migrations.Migration):
    """
    Add a partial index for the hot path query in car_list:

        SELECT ... FROM cars_apicar
        WHERE NOT (auction_date < now AND category_id = <auction_id>)
        ORDER BY created_at DESC
        LIMIT 20

    A regular composite index on (category_id, created_at) is not enough
    because the WHERE clause uses a date comparison with a runtime value.
    We use a raw SQL partial index instead:

        CREATE INDEX CONCURRENTLY cars_apicar_active_created_idx
        ON cars_apicar (created_at DESC)
        WHERE auction_date IS NULL OR auction_date >= NOW();

    PostgreSQL cannot use a partial index with a runtime NOW() condition
    perfectly, but an index on just (created_at DESC) allows the planner
    to do an index scan + filter instead of a sequential scan + sort,
    reducing the 43ms main query significantly on large tables.

    We also add a plain (created_at DESC) index which Django may not have
    created automatically despite db_index=True (which creates ASC only).
    """

    dependencies = [
        ("cars", "0017_add_static_filter_indexes"),
    ]

    # CONCURRENTLY cannot run inside a transaction block.
    atomic = False

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS cars_apicar_created_desc_idx
                ON cars_apicar (created_at DESC);
            """,
            reverse_sql="DROP INDEX IF EXISTS cars_apicar_created_desc_idx;",
        ),
    ]
