from django.db import models
from django_tenants.models import TenantMixin, DomainMixin


class Tenant(TenantMixin):
    name = models.CharField(max_length=100)
    logo = models.URLField(max_length=500, blank=True, null=True)
    favicon = models.URLField(max_length=500, blank=True, null=True)
    primary_color = models.CharField(max_length=7, default="#2563eb", help_text="Hex color e.g. #2563eb")
    secondary_color = models.CharField(max_length=7, default="#1e3a8a", help_text="Hex color e.g. #1e3a8a")
    accent_color = models.CharField(max_length=7, default="#3b82f6", help_text="Hex color e.g. #3b82f6")
    footer_text = models.CharField(max_length=255, blank=True, null=True, verbose_name="نص الفوتر (عربي)")
    footer_text_en = models.CharField(max_length=255, blank=True, null=True, verbose_name="Footer Text (EN)")

    # Business Information
    about = models.TextField(blank=True, null=True, verbose_name="نبذة عنا (عربي)")
    about_en = models.TextField(blank=True, null=True, verbose_name="About Us (EN)")
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="رقم الهاتف")
    phone2 = models.CharField(max_length=20, blank=True, null=True, verbose_name="رقم هاتف إضافي")
    whatsapp = models.CharField(max_length=20, blank=True, null=True, verbose_name="واتساب")
    email = models.EmailField(blank=True, null=True, verbose_name="البريد الإلكتروني")
    address = models.CharField(max_length=255, blank=True, null=True, verbose_name="العنوان (عربي)")
    address_en = models.CharField(max_length=255, blank=True, null=True, verbose_name="Address (EN)")
    city = models.CharField(max_length=100, blank=True, null=True, verbose_name="المدينة (عربي)")
    city_en = models.CharField(max_length=100, blank=True, null=True, verbose_name="City (EN)")
    map_url = models.URLField(max_length=500, blank=True, null=True, verbose_name="رابط الخريطة")
    working_hours = models.CharField(max_length=100, blank=True, null=True, verbose_name="ساعات العمل (عربي)")
    working_hours_en = models.CharField(max_length=100, blank=True, null=True, verbose_name="Working Hours (EN)")

    # Contact Person
    contact_person_name = models.CharField(max_length=100, blank=True, null=True, verbose_name="اسم المسؤول")
    contact_person_photo = models.ImageField(upload_to='contact_photos/', blank=True, null=True, verbose_name="صورة المسؤول")

    # Social Media
    instagram = models.URLField(max_length=255, blank=True, null=True, verbose_name="انستقرام")
    twitter = models.URLField(max_length=255, blank=True, null=True, verbose_name="تويتر")
    facebook = models.URLField(max_length=255, blank=True, null=True, verbose_name="فيسبوك")
    tiktok = models.URLField(max_length=255, blank=True, null=True, verbose_name="تيك توك")
    snapchat = models.URLField(max_length=255, blank=True, null=True, verbose_name="سناب شات")
    youtube = models.URLField(max_length=255, blank=True, null=True, verbose_name="يوتيوب")

    # SMTP Email Settings
    email_host = models.CharField(max_length=255, blank=True, default='smtp.gmail.com', verbose_name="SMTP Host")
    email_port = models.IntegerField(default=587, verbose_name="SMTP Port")
    email_username = models.CharField(max_length=255, blank=True, verbose_name="SMTP Username")
    email_password = models.CharField(max_length=255, blank=True, verbose_name="SMTP Password")
    email_use_tls = models.BooleanField(default=True, verbose_name="Use TLS")
    email_from_name = models.CharField(max_length=100, blank=True, verbose_name="From Name")

    created_at = models.DateTimeField(auto_now_add=True)

    auto_create_schema = True

    def __str__(self):
        return self.name


class Domain(DomainMixin):
    pass
