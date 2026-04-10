from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0019_add_ofleet_split_by_make'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='landing_design',
            field=models.CharField(
                choices=[
                    ('cosmos', '🌌 Cosmos (Dark Animated)'),
                    ('minimal', '⚡ Minimal (Clean Light)'),
                    ('bold', '🏆 Bold (Full Hero)'),
                ],
                default='cosmos',
                help_text='اختر تصميم صفحة الدخول الرئيسية للموقع',
                max_length=10,
                verbose_name='تصميم صفحة الدخول',
            ),
        ),
    ]
