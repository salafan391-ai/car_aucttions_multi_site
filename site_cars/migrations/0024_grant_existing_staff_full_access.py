from django.db import migrations


def grant_existing_staff(apps, schema_editor):
    """Preserve today's access for staff who predate the permission system.

    Before StaffAccess, ``is_staff`` alone meant full dashboard access. Section
    checks default to deny, so any existing non-superuser staff account would
    silently lose access on deploy. Grant them every section — that is exactly
    what they had — and let the site admin narrow it down from the UI.
    """
    User = apps.get_model("auth", "User")
    StaffAccess = apps.get_model("site_cars", "StaffAccess")

    for user in User.objects.filter(is_staff=True, is_superuser=False):
        StaffAccess.objects.get_or_create(
            user_id=user.pk,
            defaults={
                "can_cars": True,
                "can_sales": True,
                "can_orders": True,
                "can_reviews": True,
            },
        )


def noop(apps, schema_editor):
    """StaffAccess rows go away with the table; nothing to undo here."""


class Migration(migrations.Migration):

    dependencies = [
        ("site_cars", "0023_staffaccess"),
    ]

    operations = [
        migrations.RunPython(grant_existing_staff, noop),
    ]
