from django.db import migrations


def backfill_items(apps, schema_editor):
    """Give every existing invoice a line item built from its single car +
    price, so the new multi-car logic treats old and new invoices the same."""
    SiteBill = apps.get_model('site_cars', 'SiteBill')
    SiteBillItem = apps.get_model('site_cars', 'SiteBillItem')
    for bill in SiteBill.objects.all():
        if bill.items.exists():
            continue
        title = ''
        if bill.site_car_id and bill.site_car:
            title = bill.site_car.title or ''
        if not title:
            title = bill.description or 'سيارة'
        SiteBillItem.objects.create(
            bill=bill,
            site_car_id=bill.site_car_id,
            title=title,
            price=bill.price or 0,
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('site_cars', '0014_sitebill_buyer_user_sitebillitem'),
    ]

    operations = [
        migrations.RunPython(backfill_items, noop),
    ]
