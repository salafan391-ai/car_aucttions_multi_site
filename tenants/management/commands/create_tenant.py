"""
Management command to create a new tenant with domain
"""
from django.core.management.base import BaseCommand
from tenants.models import Tenant, Domain


class Command(BaseCommand):
    help = 'Create a new tenant with domain'

    def add_arguments(self, parser):
        parser.add_argument('schema_name', type=str, help='Schema name (e.g., tenant1)')
        parser.add_argument('domain', type=str, help='Domain name (e.g., tenant1.yourdomain.com)')
        parser.add_argument('--name', type=str, help='Tenant display name', default='')

    def handle(self, *args, **options):
        schema_name = options['schema_name']
        domain_name = options['domain']
        tenant_name = options['name'] or schema_name.title()

        # Check if tenant already exists
        if Tenant.objects.filter(schema_name=schema_name).exists():
            self.stdout.write(self.style.ERROR(f'Tenant with schema "{schema_name}" already exists!'))
            return

        # Check if domain already exists
        if Domain.objects.filter(domain=domain_name).exists():
            self.stdout.write(self.style.ERROR(f'Domain "{domain_name}" already exists!'))
            return

        # Create tenant
        self.stdout.write(f'Creating tenant: {tenant_name}...')
        tenant = Tenant.objects.create(
            schema_name=schema_name,
            name=tenant_name,
            primary_color='#2563eb',
            secondary_color='#1e3a8a',
            accent_color='#3b82f6',
        )
        self.stdout.write(self.style.SUCCESS(f'✓ Tenant "{tenant_name}" created'))

        # Create domain
        self.stdout.write(f'Creating domain: {domain_name}...')
        domain = Domain.objects.create(
            domain=domain_name,
            tenant=tenant,
            is_primary=True
        )
        self.stdout.write(self.style.SUCCESS(f'✓ Domain "{domain_name}" created'))

        self.stdout.write(self.style.SUCCESS(f'\n🎉 Tenant successfully created!'))
        self.stdout.write(f'   Schema: {tenant.schema_name}')
        self.stdout.write(f'   Name: {tenant.name}')
        self.stdout.write(f'   Domain: {domain.domain}')
        self.stdout.write(f'\n   Access at: http://{domain.domain}/')
