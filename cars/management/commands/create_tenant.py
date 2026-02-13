from django.core.management.base import BaseCommand
from tenants.models import Tenant, Domain


class Command(BaseCommand):
    help = "Create a new tenant with a domain"

    def add_arguments(self, parser):
        parser.add_argument("schema_name", type=str)
        parser.add_argument("name", type=str)
        parser.add_argument("domain", type=str)

    def handle(self, *args, **options):
        schema = options["schema_name"]
        name = options["name"]
        domain = options["domain"]

        if Tenant.objects.filter(schema_name=schema).exists():
            self.stdout.write(self.style.WARNING(f"Tenant '{schema}' already exists."))
            return

        t = Tenant(schema_name=schema, name=name)
        t.save()
        Domain.objects.create(domain=domain, tenant=t, is_primary=True)
        self.stdout.write(self.style.SUCCESS(f"Tenant '{name}' created with domain '{domain}'"))
