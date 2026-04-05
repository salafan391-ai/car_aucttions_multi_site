from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cars", "0023_add_make_name_to_pdfexport"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        DELETE FROM cars_wishlist;

                        ALTER TABLE cars_wishlist
                            DROP CONSTRAINT IF EXISTS cars_wishlist_user_id_car_id_0b104735_uniq,
                            DROP CONSTRAINT IF EXISTS cars_wishlist_user_id_a25befc2_fk_auth_user_id,
                            DROP COLUMN IF EXISTS user_id;

                        DROP INDEX IF EXISTS cars_wishli_user_id_477742_idx;
                        DROP INDEX IF EXISTS cars_wishlist_user_id_a25befc2;

                        ALTER TABLE cars_wishlist
                            ADD COLUMN session_key VARCHAR(40) NOT NULL DEFAULT '';

                        ALTER TABLE cars_wishlist
                            ADD CONSTRAINT cars_wishlist_session_key_car_id_uniq UNIQUE (session_key, car_id);

                        CREATE INDEX cars_wishli_session_created_idx
                            ON cars_wishlist (session_key, created_at);

                        CREATE INDEX cars_wishlist_session_key_idx
                            ON cars_wishlist (session_key);
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.RemoveField(model_name="wishlist", name="user"),
                migrations.AddField(
                    model_name="wishlist",
                    name="session_key",
                    field=models.CharField(max_length=40, db_index=True, default=""),
                    preserve_default=False,
                ),
                migrations.AlterUniqueTogether(
                    name="wishlist",
                    unique_together={("session_key", "car")},
                ),
            ],
        ),
    ]
