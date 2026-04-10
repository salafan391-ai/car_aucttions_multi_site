from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0023_landing_design_dashboard'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tenant',
            name='landing_design',
            field=models.CharField(
                choices=[
                    ('cosmos',    '🌌 Cosmos (Dark Animated)'),
                    ('minimal',   '⚡ Minimal (Clean Light)'),
                    ('bold',      '🏆 Bold (Full Hero)'),
                    ('luxury',    '✨ Luxury (Gold Dark)'),
                    ('neon',      '🔮 Neon (Cyberpunk)'),
                    ('desert',    '🏜️ Desert (Arabic)'),
                    ('split',     '▌ Split (Hero Panel)'),
                    ('dashboard', '📊 Dashboard (Clean Stats)'),
                    ('cockpit',   '🎛️ Cockpit (Car Gauges)'),
                ],
                default='cosmos',
                help_text='اختر تصميم صفحة الدخول الرئيسية للموقع',
                max_length=10,
                verbose_name='تصميم صفحة الدخول',
            ),
        ),
    ]
