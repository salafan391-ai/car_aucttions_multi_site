from django.db import migrations


def seed(apps, schema_editor):
    """Make the existing japan_market category a market tab, and carry over any
    tenant that had show_japan_market=True into the new enabled_markets list."""
    Category = apps.get_model("cars", "Category")
    Tenant = apps.get_model("tenants", "Tenant")

    Category.objects.filter(name="japan_market").update(
        is_market_tab=True, label_ar="سيارات يابانية", label_en="Japanese", tab_order=1,
    )

    for t in Tenant.objects.filter(show_japan_market=True):
        markets = list(t.enabled_markets or [])
        if "japan_market" not in markets:
            markets.append("japan_market")
            t.enabled_markets = markets
            t.save(update_fields=["enabled_markets"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("cars", "0037_alter_category_options_category_is_market_tab_and_more"),
        ("tenants", "0080_tenant_enabled_markets"),
    ]

    operations = [migrations.RunPython(seed, noop)]
