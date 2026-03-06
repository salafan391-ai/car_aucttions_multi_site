from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django_tenants.utils import schema_context
import os


class Command(BaseCommand):
    help = (
        "Create superuser from env vars (SUPERUSER_USERNAME, SUPERUSER_EMAIL, SUPERUSER_PASSWORD) "
        "Optionally create inside a tenant schema with --schema <schema_name>"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema",
            dest="schema",
            help="Create the superuser inside the given tenant schema (django-tenants).",
            default=None,
        )

    def handle(self, *args, **options):
        User = get_user_model()
        username = os.environ.get("SUPERUSER_USERNAME", "admin")
        email = os.environ.get("SUPERUSER_EMAIL", "admin@example.com")
        password = os.environ.get("SUPERUSER_PASSWORD", "admin123")
        schema = options.get("schema") or os.environ.get("SUPERUSER_SCHEMA")

        def _create():
            if User.objects.filter(username=username).exists():
                self.stdout.write(self.style.WARNING(f"User '{username}' already exists."))
                return False

            User.objects.create_superuser(username=username, email=email, password=password)
            return True

        if schema:
            # Create the user inside the tenant/public schema context
            try:
                with schema_context(schema):
                    created = _create()
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed setting schema '{schema}': {e}"))
                return
            if created:
                self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' created successfully in schema '{schema}'."))
        else:
            created = _create()
            if created:
                self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' created successfully in default schema."))
