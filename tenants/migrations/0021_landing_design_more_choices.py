from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0020_add_landing_design'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tenant',
            name='landing_design',
            field=models.CharField(
                choices=[
                    ('cosmos',  '🌌 Cosmos (Dark Animated)'),
                    ('minimal', '⚡ Minimal (Clean Light)'),
                    ('bold',    '🏆 Bold (Full Hero)'),
                    ('luxury',  '✨ Luxury (Gold Dark)'),
                    ('neon',    '🔮 Neon (Cyberpunk)'),
                    ('desert',  '🏜️ Desert (Arabic)'),
                    ('split',   '▌ Split (Hero Panel)'),
                ],
                default='cosmos',
                help_text='اختر تصميم صفحة الدخول الرئيسية للموقع',
                max_length=10,
                verbose_name='تصميم صفحة الدخول',
            ),
        ),
    ]
