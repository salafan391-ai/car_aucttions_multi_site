from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0021_landing_design_more_choices'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='landing_is_active',
            field=models.BooleanField(
                default=True,
                help_text='عند التعطيل يتم التوجيه مباشرة إلى الصفحة الرئيسية بدون صفحة الدخول',
                verbose_name='تفعيل صفحة الدخول',
            ),
        ),
    ]
