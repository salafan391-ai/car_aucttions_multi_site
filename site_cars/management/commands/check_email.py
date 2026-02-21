"""
Management command to diagnose and test tenant email configuration.

Usage:
    heroku run python manage.py check_email --app tenant-cars
    heroku run python manage.py check_email --schema tradbull --app tenant-cars
    heroku run python manage.py check_email --schema tradbull --send test@example.com --app tenant-cars
"""
from django.core.management.base import BaseCommand
from django.db import connection
from tenants.models import Tenant


class Command(BaseCommand):
    help = 'Check and test tenant email configuration'

    def add_arguments(self, parser):
        parser.add_argument('--schema', type=str, help='Specific schema to check (default: all non-public)')
        parser.add_argument('--send', type=str, help='Send a test email to this address')

    def handle(self, *args, **options):
        schema_filter = options.get('schema')
        send_to = options.get('send')

        tenants = Tenant.objects.exclude(schema_name='public')
        if schema_filter:
            tenants = tenants.filter(schema_name=schema_filter)

        if not tenants.exists():
            self.stdout.write(self.style.ERROR('No tenants found.'))
            return

        for tenant in tenants:
            self.stdout.write(self.style.HTTP_INFO(f'\n=== Tenant: {tenant.name} (schema: {tenant.schema_name}) ==='))
            self.stdout.write(f'  email (business contact): "{tenant.email}"')
            self.stdout.write(f'  email_host:              "{tenant.email_host}"')
            self.stdout.write(f'  email_port:              {tenant.email_port}')
            self.stdout.write(f'  email_username (SMTP):   "{tenant.email_username}"')
            self.stdout.write(f'  email_password set:      {"YES ✓" if tenant.email_password else "NO ✗ <-- MISSING"}')
            self.stdout.write(f'  email_use_tls:           {tenant.email_use_tls}')
            self.stdout.write(f'  email_from_name:         "{tenant.email_from_name}"')

            # Show superusers who will receive order notifications
            from django.contrib.auth.models import User
            superusers = User.objects.filter(is_superuser=True, is_active=True)
            self.stdout.write(f'\n  Superusers (will receive order emails):')
            for su in superusers:
                has_email = bool(su.email)
                marker = '✓' if has_email else '✗ NO EMAIL SET'
                self.stdout.write(f'    - {su.username}: "{su.email}" {marker}')

            # Diagnose issues
            issues = []
            if not tenant.email:
                issues.append('❌ "البريد الإلكتروني" (email) is empty — admin will not receive order notifications')
            if not tenant.email_username:
                issues.append('❌ SMTP Username is empty — cannot send any emails')
            if not tenant.email_password:
                issues.append('❌ SMTP Password is empty — cannot send any emails')
            if not tenant.email_host:
                issues.append('❌ SMTP Host is empty')

            if issues:
                self.stdout.write(self.style.ERROR('\n  ISSUES:'))
                for issue in issues:
                    self.stdout.write(self.style.ERROR(f'    {issue}'))
            else:
                self.stdout.write(self.style.SUCCESS('\n  Config looks complete ✓'))

            # Test send if requested
            if send_to and not issues:
                self.stdout.write(f'\n  Sending test email to {send_to} ...')
                # Switch to tenant schema for SiteEmailLog
                connection.set_schema(tenant.schema_name)
                from site_cars.email_utils import send_tenant_email
                ok = send_tenant_email(
                    recipient_email=send_to,
                    subject=f'Test Email from {tenant.name}',
                    body_html=f'<p dir="rtl">هذه رسالة تجريبية من موقع <strong>{tenant.name}</strong>.</p><p>This is a test email from <strong>{tenant.name}</strong>.</p>',
                    email_type='test',
                )
                if ok:
                    self.stdout.write(self.style.SUCCESS(f'  ✓ Test email sent successfully to {send_to}'))
                else:
                    self.stdout.write(self.style.ERROR(f'  ✗ Test email FAILED — check SiteEmailLog in admin for error details'))
            elif send_to and issues:
                self.stdout.write(self.style.WARNING('  Skipping test send due to configuration issues above.'))

        self.stdout.write('\n')
        self.stdout.write(self.style.WARNING(
            'To fix: Go to Heroku admin → Tenants → [your tenant] and fill in:\n'
            '  - البريد الإلكتروني  (your admin email to RECEIVE notifications)\n'
            '  - SMTP Username      (Gmail address used to SEND)\n'
            '  - SMTP Password      (Gmail App Password — NOT your login password)\n'
            '  - SMTP Host          smtp.gmail.com\n'
            '  - SMTP Port          587\n'
            '  Get App Password at: https://myaccount.google.com/apppasswords'
        ))
