from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cars", "0031_apicar_inspection_report_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="apicar",
            name="markers",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
