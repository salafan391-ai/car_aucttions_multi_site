from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0024_landing_design_cockpit'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='car_display',
            field=models.CharField(
                choices=[
                    ('classic', '🃏 Classic (بطاقات بيضاء)'),
                    ('dark',    '🌙 Dark (بطاقات داكنة)'),
                    ('minimal', '✦ Minimal (نظيف مسطح)'),
                    ('bold',    '🎨 Bold (صورة كاملة)'),
                    ('cockpit', '🎛️ Cockpit (لوحة القيادة)'),
                ],
                default='classic',
                max_length=10,
                verbose_name='ثيم بطاقات السيارات',
                help_text='اختر التصميم البصري لبطاقات السيارات في صفحة القائمة',
            ),
        ),
    ]
