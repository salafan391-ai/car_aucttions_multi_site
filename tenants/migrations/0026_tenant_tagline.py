from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0025_tenant_car_display'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='tagline',
            field=models.CharField(
                max_length=255,
                blank=True,
                null=True,
                verbose_name='شعار الموقع (عربي)',
                help_text='النص الذي يظهر بتأثير الكتابة في الصفحة الرئيسية وصفحة الهبوط',
            ),
        ),
        migrations.AddField(
            model_name='tenant',
            name='tagline_en',
            field=models.CharField(
                max_length=255,
                blank=True,
                null=True,
                verbose_name='Site Tagline (EN)',
                help_text='Shown with typewriter effect on the home and landing pages',
            ),
        ),
    ]
