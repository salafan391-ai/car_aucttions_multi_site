from django.db import models
from django_tenants.models import TenantMixin, DomainMixin


class Tenant(TenantMixin):
    name = models.CharField(max_length=100)
    logo = models.ImageField(upload_to='tenant_logos/', blank=True, null=True, verbose_name="الشعار")
    favicon = models.ImageField(upload_to='tenant_favicons/', blank=True, null=True, verbose_name="أيقونة الموقع")
    hero_image = models.ImageField(upload_to='tenant_hero/', blank=True, null=True, verbose_name="صورة الخلفية الرئيسية", help_text="صورة خلفية الصفحة الرئيسية")
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


class TenantHeroImage(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='hero_images', verbose_name="الموقع")
    image = models.ImageField(upload_to='tenant_hero/', verbose_name="الصورة")
    order = models.PositiveIntegerField(default=0, verbose_name="الترتيب")

    class Meta:
        ordering = ['order']
        verbose_name = "صورة الهيرو"
        verbose_name_plural = "صور الهيرو"

    def __str__(self):
        return f"{self.tenant.name} - Hero {self.order}"


class TenantPhoneNumber(models.Model):
    """
    Multiple phone numbers for a tenant with different types
    """
    PHONE_TYPES = [
        ('general', 'عام'),
        ('sales', 'مبيعات'),
        ('support', 'دعم فني'),
        ('whatsapp', 'واتساب'),
        ('manager', 'مدير'),
        ('other', 'أخرى'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='phone_numbers', verbose_name="الموقع")
    phone_number = models.CharField(max_length=20, verbose_name="رقم الهاتف")
    phone_type = models.CharField(max_length=20, choices=PHONE_TYPES, default='general', verbose_name="نوع الرقم")
    label = models.CharField(max_length=50, blank=True, help_text="مثل: قسم المبيعات، الفرع الرئيسي", verbose_name="تسمية إضافية")
    is_primary = models.BooleanField(default=False, verbose_name="رقم رئيسي")
    is_active = models.BooleanField(default=True, verbose_name="نشط")
    order = models.IntegerField(default=0, verbose_name="الترتيب")
    
    class Meta:
        ordering = ['order', '-is_primary', 'phone_type']
        verbose_name = "رقم هاتف"
        verbose_name_plural = "أرقام الهواتف"
    
    def __str__(self):
        type_display = dict(self.PHONE_TYPES).get(self.phone_type, self.phone_type)
        return f"{self.phone_number} ({type_display})"
    
    def save(self, *args, **kwargs):
        # If this is set as primary, unset other primary numbers
        if self.is_primary:
            TenantPhoneNumber.objects.filter(tenant=self.tenant, is_primary=True).update(is_primary=False)
        super().save(*args, **kwargs)
