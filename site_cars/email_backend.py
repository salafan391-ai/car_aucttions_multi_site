import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from django.core.mail.backends.base import BaseEmailBackend
from django.db import connection

from tenants.models import Tenant


class TenantEmailBackend(BaseEmailBackend):
    """Custom email backend that uses the current tenant's SMTP settings."""

    def send_messages(self, email_messages):
        num_sent = 0
        config = self._get_config()
        if not config:
            return 0

        for message in email_messages:
            try:
                msg = MIMEMultipart('alternative')
                msg['Subject'] = message.subject
                msg['From'] = f"{config['from_name']} <{config['from_email']}>"
                msg['To'] = ', '.join(message.to)

                body = message.body
                if message.content_subtype == 'html':
                    msg.attach(MIMEText(body, 'html', 'utf-8'))
                else:
                    msg.attach(MIMEText(body, 'plain', 'utf-8'))

                if config['use_tls']:
                    server = smtplib.SMTP(config['host'], config['port'])
                    server.starttls()
                else:
                    server = smtplib.SMTP_SSL(config['host'], config['port'])

                server.login(config['username'], config['password'])
                server.sendmail(config['from_email'], message.to, msg.as_string())
                server.quit()
                num_sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
        return num_sent

    def _get_config(self):
        schema = connection.schema_name
        try:
            tenant = Tenant.objects.get(schema_name=schema)
        except Tenant.DoesNotExist:
            return None

        if not tenant.email_username or not tenant.email_host:
            return None

        return {
            'host': tenant.email_host,
            'port': tenant.email_port,
            'username': tenant.email_username,
            'password': tenant.email_password,
            'use_tls': tenant.email_use_tls,
            'from_name': tenant.email_from_name or tenant.name,
            'from_email': tenant.email_username,
        }
