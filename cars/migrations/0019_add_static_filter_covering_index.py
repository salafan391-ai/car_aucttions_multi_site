# Generated manually on 2026-03-06

from django.db import migrations


class Migration(migrations.Migration):
    """
    Add a covering index to accelerate the static-filter single-pass query:

        SELECT year, body_id, fuel, transmission,
               seat_count, color_id, seat_color_id
        FROM cars_apicar
        LEFT JOIN cars_category ON ...
        WHERE NOT (cars_category.name = 'auction')
          AND NOT (auction_date < now AND ...)
        -- no LIMIT, fetches all rows

    The new approach uses a single .values() scan across all 7 filter
    columns. PostgreSQL does a sequential scan because no index covers
    all these columns together.

    Index strategy:
      - Key column: category_id  (used in WHERE NOT category='auction')
      - INCLUDE columns: year, body_id, fuel, transmission,
                         seat_count, color_id, seat_color_id
        (carried along for index-only scan — not part of the B-tree key)

    With this index PostgreSQL can satisfy the query entirely from the
    index pages (index-only scan) rather than hitting the heap.
    This turns the 259ms full sequential scan into a fast index-only scan.

    Requires PostgreSQL 11+ for INCLUDE support (Heroku Postgres: yes).
    Uses CONCURRENTLY so it doesn't lock the table during creation.
    """

    dependencies = [
        ("cars", "0018_add_main_list_partial_index"),
    ]

    atomic = False  # CONCURRENTLY cannot run inside a transaction

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS cars_apicar_filter_covering_idx
                ON cars_apicar (category_id)
                INCLUDE (year, body_id, fuel, transmission, seat_count, color_id, seat_color_id);
            """,
            reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS cars_apicar_filter_covering_idx;",
        ),
    ]
