from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0017_add_eid_is_active'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='ofleet_username',
            field=models.CharField(
                blank=True,
                max_length=150,
                verbose_name='ofleet اسم المستخدم',
                help_text='اسم المستخدم لـ API تصدير PDF من ofleet0.com',
            ),
        ),
        migrations.AddField(
            model_name='tenant',
            name='ofleet_password',
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name='ofleet كلمة المرور',
                help_text='كلمة المرور لـ API تصدير PDF من ofleet0.com',
            ),
        ),
    ]
