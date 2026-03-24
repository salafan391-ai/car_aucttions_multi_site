from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cars', '0021_add_name_ar_to_carmodel'),
    ]

    operations = [
        migrations.CreateModel(
            name='PdfExport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('auction_name', models.CharField(max_length=200, verbose_name='اسم المزاد')),
                ('schema_name', models.CharField(blank=True, max_length=100, verbose_name='الموقع (schema)')),
                ('status', models.CharField(
                    choices=[('pending', 'جاري الإعداد'), ('complete', 'جاهز للتحميل'), ('failed', 'فشل')],
                    db_index=True, default='pending', max_length=20,
                )),
                ('pdf_file', models.FileField(blank=True, null=True, upload_to='auction_pdfs/', verbose_name='ملف PDF')),
                ('error_detail', models.TextField(blank=True, verbose_name='سبب الخطأ')),
                ('entry_count', models.IntegerField(default=0, verbose_name='عدد السيارات')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'verbose_name': 'تصدير PDF',
                'verbose_name_plural': 'تصديرات PDF',
                'ordering': ['-created_at'],
            },
        ),
    ]
