# Generated for is_new flag on ApiCar

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cars', '0025_remove_wishlist_cars_wishli_user_id_477742_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='apicar',
            name='is_new',
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
