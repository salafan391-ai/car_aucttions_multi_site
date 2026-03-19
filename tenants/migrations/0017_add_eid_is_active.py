from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0016_add_eid_theme'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='eid_is_active',
            field=models.BooleanField(default=False, verbose_name='تفعيل زينة العيد', help_text='عند التفعيل تظهر زينة العيد (بالونات ونصوص متحركة) في جميع صفحات الموقع.'),
        ),
    ]
