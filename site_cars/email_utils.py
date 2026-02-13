import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from django.db import connection
from django.contrib.auth.models import User

from tenants.models import Tenant


def get_tenant_email_config():
    """Get SMTP config for the current tenant."""
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


def send_tenant_email(recipient_email, subject, body_html, email_type='custom', recipient_user=None):
    """Send an email using the current tenant's SMTP settings and log it."""
    from .models import SiteEmailLog

    config = get_tenant_email_config()

    log = SiteEmailLog.objects.create(
        recipient_email=recipient_email,
        recipient_user=recipient_user,
        subject=subject,
        body=body_html,
        email_type=email_type,
        status='pending',
    )

    if not config:
        log.status = 'failed'
        log.error_message = 'SMTP settings not configured for this site.'
        log.save(update_fields=['status', 'error_message'])
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{config['from_name']} <{config['from_email']}>"
        msg['To'] = recipient_email

        msg.attach(MIMEText(body_html, 'html', 'utf-8'))

        if config['use_tls']:
            server = smtplib.SMTP(config['host'], config['port'])
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(config['host'], config['port'])

        server.login(config['username'], config['password'])
        server.sendmail(config['from_email'], recipient_email, msg.as_string())
        server.quit()

        log.status = 'sent'
        log.save(update_fields=['status'])
        return True

    except Exception as e:
        log.status = 'failed'
        log.error_message = str(e)
        log.save(update_fields=['status', 'error_message'])
        return False


def send_order_placed_email(order):
    """Send notification when a new order is placed."""
    subject = f"طلب جديد #{order.pk} - {order.car.title}"
    body = f"""
    <div dir="rtl" style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #2563eb;">تم استلام طلبك بنجاح!</h2>
        <p>مرحباً {order.user.get_short_name() or order.user.username}،</p>
        <p>تم استلام طلبك رقم <strong>#{order.pk}</strong> بنجاح وسيتم مراجعته قريباً.</p>
        <div style="background: #f3f4f6; border-radius: 12px; padding: 16px; margin: 16px 0;">
            <p><strong>السيارة:</strong> {order.car.title}</p>
            <p><strong>السعر المعروض:</strong> {order.offer_price:,.0f} ₩</p>
            <p><strong>الحالة:</strong> قيد المراجعة</p>
        </div>
        <p>سنتواصل معك قريباً بخصوص طلبك.</p>
        <p style="color: #9ca3af; font-size: 12px;">هذه رسالة تلقائية، لا تقم بالرد عليها.</p>
    </div>
    """
    if order.user.email:
        send_tenant_email(order.user.email, subject, body, 'order_placed', order.user)


def send_order_status_email(order):
    """Send notification when order status changes."""
    status_labels = {
        'pending': 'قيد المراجعة',
        'accepted': 'مقبول',
        'rejected': 'مرفوض',
        'completed': 'مكتمل',
    }
    status_colors = {
        'pending': '#f59e0b',
        'accepted': '#3b82f6',
        'rejected': '#ef4444',
        'completed': '#22c55e',
    }
    status_label = status_labels.get(order.status, order.status)
    status_color = status_colors.get(order.status, '#6b7280')

    subject = f"تحديث حالة طلبك #{order.pk} - {status_label}"
    body = f"""
    <div dir="rtl" style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #2563eb;">تحديث حالة الطلب</h2>
        <p>مرحباً {order.user.get_short_name() or order.user.username}،</p>
        <p>تم تحديث حالة طلبك رقم <strong>#{order.pk}</strong>.</p>
        <div style="background: #f3f4f6; border-radius: 12px; padding: 16px; margin: 16px 0;">
            <p><strong>السيارة:</strong> {order.car.title}</p>
            <p><strong>الحالة الجديدة:</strong> <span style="color: {status_color}; font-weight: bold;">{status_label}</span></p>
        </div>
        {"<p><strong>ملاحظات الإدارة:</strong> " + order.admin_notes + "</p>" if order.admin_notes else ""}
        <p style="color: #9ca3af; font-size: 12px;">هذه رسالة تلقائية، لا تقم بالرد عليها.</p>
    </div>
    """
    if order.user.email:
        send_tenant_email(order.user.email, subject, body, 'order_status', order.user)


def send_broadcast_email(subject, body_html, sender_user=None):
    """Send an email to all users with email addresses."""
    users = User.objects.exclude(email='').exclude(email__isnull=True)
    count = 0
    for user in users:
        if send_tenant_email(user.email, subject, body_html, 'broadcast', user):
            count += 1
    return count
