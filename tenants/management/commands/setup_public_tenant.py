"""
Management command to create or fix the public tenant
"""
from django.core.management.base import BaseCommand
from tenants.models import Tenant, Domain
import os


class Command(BaseCommand):
    help = 'Create or verify the public tenant and register the current domain'

    def handle(self, *args, **options):
        # Create or get public tenant
        public_tenant, created = Tenant.objects.get_or_create(
            schema_name='public',
            defaults={
                'name': 'Public Schema',
                'primary_color': '#2563eb',
                'secondary_color': '#1e3a8a',
                'accent_color': '#3b82f6',
            }
        )

        if created:
            self.stdout.write(self.style.SUCCESS('✓ Public tenant created'))
        else:
            self.stdout.write(self.style.SUCCESS('✓ Public tenant already exists'))

        # Collect all domain names to register for the public tenant
        domains_to_register = ['localhost', '127.0.0.1']

        # Railway: RAILWAY_PUBLIC_DOMAIN is set automatically
        railway_domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
        if railway_domain:
            domains_to_register.append(railway_domain)

        # Also support explicit ALLOWED_HOSTS entries
        allowed_hosts = os.environ.get('ALLOWED_HOSTS', '')
        for h in allowed_hosts.split(','):
            h = h.strip().lstrip('*').lstrip('.')
            if h and h not in domains_to_register:
                domains_to_register.append(h)

        first = True
        for domain_name in domains_to_register:
            if not domain_name:
                continue
            domain, created = Domain.objects.get_or_create(
                domain=domain_name,
                defaults={
                    'tenant': public_tenant,
                    'is_primary': first,
                }
            )
            # If domain exists but points to wrong tenant, fix it
            if not created and domain.tenant != public_tenant:
                domain.tenant = public_tenant
                domain.save()
                self.stdout.write(self.style.WARNING(f'  ↻ Reassigned domain "{domain_name}" to public tenant'))
            else:
                status = '✓ Created' if created else '✓ Already exists'
                self.stdout.write(f'  {status}: {domain_name}')
            first = False

        self.stdout.write(self.style.SUCCESS('\n🎉 Public tenant setup complete'))


        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Domain created: {domain_name}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'✓ Domain already exists: {domain_name}'))

        self.stdout.write(self.style.SUCCESS('\n🎉 Public tenant is ready!'))
        self.stdout.write(f'   Access admin at: https://{domain_name}/admin/')
