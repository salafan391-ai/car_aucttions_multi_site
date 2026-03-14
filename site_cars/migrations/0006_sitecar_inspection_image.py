from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('site_cars', '0005_siterating_is_approved'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitecar',
            name='inspection_image',
            field=models.ImageField(blank=True, null=True, upload_to='site_cars/inspections/', verbose_name='صورة الفحص'),
        ),
    ]
