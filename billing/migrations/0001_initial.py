import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Subscription",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("stripe_customer_id", models.CharField(blank=True, default="", max_length=64)),
                ("stripe_subscription_id", models.CharField(blank=True, default="", max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("none", "Not subscribed"),
                            ("incomplete", "Incomplete"),
                            ("incomplete_expired", "Incomplete (expired)"),
                            ("trialing", "Trialing"),
                            ("active", "Active"),
                            ("past_due", "Past due"),
                            ("unpaid", "Unpaid"),
                            ("canceled", "Canceled"),
                        ],
                        default="none",
                        max_length=24,
                    ),
                ),
                ("current_period_end", models.DateTimeField(blank=True, null=True)),
                ("cancel_at_period_end", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subscription",
                        to="tenants.tenant",
                    ),
                ),
            ],
        ),
    ]
