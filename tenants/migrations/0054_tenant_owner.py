"""Add an ownership FK to Tenant so the SSO bridge can find an
already-provisioned site for a returning user."""
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0053_tenantheroimage_description_tenantheroimage_title_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="owned_tenants",
                to=settings.AUTH_USER_MODEL,
                verbose_name="مالك الموقع",
                help_text="حساب المستخدم (في القاعدة العامة) الذي يملك هذا الموقع — يُعبَّأ تلقائياً عند الإنشاء عبر SSO.",
            ),
        ),
    ]
