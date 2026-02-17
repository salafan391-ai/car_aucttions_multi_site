"""
Management command to create or fix the public tenant
"""
from django.core.management.base import BaseCommand
from tenants.models import Tenant, Domain


class Command(BaseCommand):
    help = 'Create or verify the public tenant'

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

        # Get your Heroku app domain
        import os
        app_name = os.environ.get('HEROKU_APP_NAME', 'localhost')
        domain_name = f"{app_name}.herokuapp.com" if app_name != 'localhost' else 'localhost'

        # Create or get domain for public tenant
        domain, created = Domain.objects.get_or_create(
            domain=domain_name,
            defaults={
                'tenant': public_tenant,
                'is_primary': True
            }
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Domain created: {domain_name}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'✓ Domain already exists: {domain_name}'))

        self.stdout.write(self.style.SUCCESS('\n🎉 Public tenant is ready!'))
        self.stdout.write(f'   Access admin at: https://{domain_name}/admin/')
