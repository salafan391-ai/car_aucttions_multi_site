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
        parser.add_argument(
            '--activate-dns', action='store_true',
            help='Also point the domain at the VPS via the Cloudflare API (grey-cloud A record)',
        )

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

        if options.get('activate_dns'):
            from tenants.cloudflare import point_domain_to_vps, CloudflareError
            self.stdout.write(f'Pointing {domain_name} at the VPS via Cloudflare...')
            try:
                msg = point_domain_to_vps(domain_name)
                self.stdout.write(self.style.SUCCESS(f'✓ DNS: {msg}'))
            except CloudflareError as e:
                self.stdout.write(self.style.WARNING(f'DNS not set ({e}) — flip it manually or retry'))

        self.stdout.write(self.style.SUCCESS(f'\n🎉 Tenant successfully created!'))
        self.stdout.write(f'   Schema: {tenant.schema_name}')
        self.stdout.write(f'   Name: {tenant.name}')
        self.stdout.write(f'   Domain: {domain.domain}')
        self.stdout.write(f'\n   Access at: http://{domain.domain}/')
