from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("site_cars", "0006_sitecar_inspection_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitecar",
            name="external_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="مفتاح استيراد خارجي — مثال: hc_896409",
                max_length=50,
                null=True,
                unique=True,
                verbose_name="المعرف الخارجي",
            ),
        ),
        migrations.AddField(
            model_name="sitecar",
            name="external_image_url",
            field=models.URLField(
                blank=True,
                help_text="يستخدم بدل رفع الصورة عند استيراد السيارة من مصدر خارجي",
                max_length=500,
                null=True,
                verbose_name="رابط الصورة الخارجي",
            ),
        ),
    ]
