from django.db import migrations, models


def seed_singleton(apps, schema_editor):
    GlobalExchangeRates = apps.get_model("tenants", "GlobalExchangeRates")
    Tenant = apps.get_model("tenants", "Tenant")

    src = Tenant.objects.exclude(schema_name="public").first()
    defaults = {
        "rate_usd": getattr(src, "rate_usd", None) or 0.00067,
        "rate_sar": getattr(src, "rate_sar", None) or 0.00250,
        "rate_aed": getattr(src, "rate_aed", None) or 0.00272,
        "rate_eur": getattr(src, "rate_eur", None) or 0.00069,
    }
    GlobalExchangeRates.objects.update_or_create(pk=1, defaults=defaults)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0029_tenant_template_theme"),
    ]

    operations = [
        migrations.CreateModel(
            name="GlobalExchangeRates",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rate_usd", models.DecimalField(decimal_places=6, default=0.00067, max_digits=10, verbose_name="سعر الدولار USD")),
                ("rate_sar", models.DecimalField(decimal_places=6, default=0.00250, max_digits=10, verbose_name="سعر الريال SAR")),
                ("rate_aed", models.DecimalField(decimal_places=6, default=0.00272, max_digits=10, verbose_name="سعر الدرهم AED")),
                ("rate_eur", models.DecimalField(decimal_places=6, default=0.00069, max_digits=10, verbose_name="سعر اليورو EUR")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "أسعار صرف العملات (عام)",
                "verbose_name_plural": "أسعار صرف العملات (عام)",
            },
        ),
        migrations.RunPython(seed_singleton, noop),
    ]
