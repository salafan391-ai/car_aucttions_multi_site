from django.db import models
from django_tenants.models import TenantMixin, DomainMixin
from site_cars.image_utils import optimize_image


class Tenant(TenantMixin):
    name = models.CharField(max_length=100)
    logo = models.ImageField(upload_to='tenant_logos/', blank=True, null=True, verbose_name="الشعار")
    favicon = models.ImageField(upload_to='tenant_favicons/', blank=True, null=True, verbose_name="أيقونة الموقع")
    hero_image = models.ImageField(upload_to='tenant_hero/', blank=True, null=True, verbose_name="صورة الخلفية الرئيسية", help_text="صورة خلفية الصفحة الرئيسية")
    show_hero = models.BooleanField(
        default=True,
        verbose_name="إظهار الهيرو في الصفحة الرئيسية",
        help_text="عند التعطيل تختفي قسم الهيرو من الصفحة الرئيسية ويُرفع المحتوى لأعلى.",
    )
    show_watermark = models.BooleanField(
        default=True,
        verbose_name="إظهار العلامة المائية على الصور",
        help_text="عند التعطيل تختفي العلامة المائية (الشعار) المرتسمة فوق صور السيارات.",
    )
    LANDING_DESIGN_CHOICES = [
        ('cosmos',  '🌌 Cosmos (Dark Animated)'),
        ('minimal', '⚡ Minimal (Clean Light)'),
        ('bold',    '🏆 Bold (Full Hero)'),
        ('luxury',  '✨ Luxury (Gold Dark)'),
        ('neon',    '🔮 Neon (Cyberpunk)'),
        ('desert',  '🏜️ Desert (Arabic)'),
        ('split',     '▌ Split (Hero Panel)'),
        ('dashboard', '📊 Dashboard (Clean Stats)'),
        ('cockpit',   '🎛️ Cockpit (Car Gauges)'),
    ]
    landing_is_active = models.BooleanField(
        default=True,
        verbose_name="تفعيل صفحة الدخول",
        help_text="عند التعطيل يتم التوجيه مباشرة إلى الصفحة الرئيسية بدون صفحة الدخول",
    )
    landing_design = models.CharField(
        max_length=10,
        choices=LANDING_DESIGN_CHOICES,
        default='cosmos',
        verbose_name="تصميم صفحة الدخول",
        help_text="اختر تصميم صفحة الدخول الرئيسية للموقع",
    )

    TEMPLATE_THEME_CHOICES = [
        ('default', 'Default (الافتراضي)'),
        ('luxury',  '✨ Luxury (فخم — ذهبي/أسود)'),
    ]
    template_theme = models.CharField(
        max_length=20,
        choices=TEMPLATE_THEME_CHOICES,
        default='default',
        verbose_name="ثيم القوالب",
        help_text="ثيم كامل يبدّل قوالب الموقع (HTML) كلياً، وليس مجرد ألوان. الافتراضي يستخدم القوالب القياسية.",
    )

    CAR_DISPLAY_CHOICES = [
        ('classic', '🃏 Classic (بطاقات بيضاء)'),
        ('dark',    '🌙 Dark (بطاقات داكنة)'),
        ('minimal', '✦ Minimal (نظيف مسطح)'),
        ('bold',    '🎨 Bold (صورة كاملة)'),
        ('cockpit', '🎛️ Cockpit (لوحة القيادة)'),
    ]
    car_display = models.CharField(
        max_length=10,
        choices=CAR_DISPLAY_CHOICES,
        default='classic',
        verbose_name="ثيم بطاقات السيارات",
        help_text="اختر التصميم البصري لبطاقات السيارات في صفحة القائمة",
    )

    THEME_CHOICES = [
        ('light',  'فاتح (Light)'),
        ('dark',   'داكن (Dark)'),
        ('desert', '🐪 صحراوي عربي (Desert Arabia)'),
        ('custom', 'مخصص (Custom Colors)'),
        ('eid',    '🎉 عيد (Eid Theme)'),
    ]
    theme = models.CharField(
        max_length=10,
        choices=THEME_CHOICES,
        default='light',
        verbose_name="ثيم الموقع",
        help_text="اختر المظهر العام للموقع. 🐪 صحراوي: تصميم عربي بألوان الصحراء والجِمال. مخصص: يستخدم الألوان المحددة أدناه.",
    )
    primary_color = models.CharField(max_length=7, default="#2563eb", help_text="Hex color e.g. #2563eb (used in Custom theme)")
    secondary_color = models.CharField(max_length=7, default="#1e3a8a", help_text="Hex color e.g. #1e3a8a (used in Custom theme)")
    accent_color = models.CharField(max_length=7, default="#3b82f6", help_text="Hex color e.g. #3b82f6 (used in Custom theme)")
    body_bg_color = models.CharField(max_length=7, default="#ffffff", blank=True, verbose_name="Body Background Color", help_text="Hex color for the page background (used in Custom theme).")
    footer_text = models.CharField(max_length=255, blank=True, null=True, verbose_name="نص الفوتر (عربي)")
    footer_text_en = models.CharField(max_length=255, blank=True, null=True, verbose_name="Footer Text (EN)")

    # Business Information
    tagline = models.CharField(max_length=255, blank=True, null=True, verbose_name="شعار الموقع (عربي)", help_text="النص الذي يظهر بتأثير الكتابة في الصفحة الرئيسية وصفحة الهبوط")
    tagline_en = models.CharField(max_length=255, blank=True, null=True, verbose_name="Site Tagline (EN)", help_text="Shown with typewriter effect on the home and landing pages")
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
    # Telegram: allow either a full URL (https://t.me/...) or a username (without @)
    telegram = models.URLField(max_length=255, blank=True, null=True, verbose_name="تيليجرام (رابط)")
    telegram_username = models.CharField(max_length=64, blank=True, null=True, verbose_name="تيليجرام (اسم المستخدم)", help_text="ادخل اسم المستخدم بدون @ — سيُحوّل تلقائياً إلى رابط t.me/username")

    # SMTP Email Settings
    email_host = models.CharField(max_length=255, blank=True, default='smtp.gmail.com', verbose_name="SMTP Host")
    email_port = models.IntegerField(default=587, verbose_name="SMTP Port")
    email_username = models.CharField(max_length=255, blank=True, verbose_name="SMTP Username")
    email_password = models.CharField(max_length=255, blank=True, verbose_name="SMTP Password")
    email_use_tls = models.BooleanField(default=True, verbose_name="Use TLS")
    email_from_name = models.CharField(max_length=100, blank=True, verbose_name="From Name")

    # Currency Exchange Rates (per 1 KRW)
    rate_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0.00067, verbose_name="سعر الدولار USD")
    rate_sar = models.DecimalField(max_digits=10, decimal_places=6, default=0.00250, verbose_name="سعر الريال SAR")
    rate_aed = models.DecimalField(max_digits=10, decimal_places=6, default=0.00272, verbose_name="سعر الدرهم AED")
    rate_eur = models.DecimalField(max_digits=10, decimal_places=6, default=0.00069, verbose_name="سعر اليورو EUR")

    created_at = models.DateTimeField(auto_now_add=True)
    eid_is_active = models.BooleanField(default=False, verbose_name="تفعيل زينة العيد", help_text="عند التفعيل تظهر زينة العيد (بالونات ونصوص متحركة) في جميع صفحات الموقع.")

    # ── Billing visibility (controlled by SaaS owner only) ───────────────
    # When False, /billing/ is inaccessible and the nav/dashboard links are
    # hidden for this tenant. Toggle this from Django admin (public schema)
    # to roll out billing tenant-by-tenant.
    billing_visible = models.BooleanField(
        default=False,
        verbose_name="إظهار الفوترة",
        help_text="عند التفعيل: تظهر صفحة الفوترة وروابطها لإداريي هذا الموقع.",
    )
    billing_amount_usd = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=400,
        verbose_name="مبلغ الفوترة (USD)",
        help_text="المبلغ الذي يدفعه هذا الموقع شهرياً بالدولار الأمريكي. الافتراضي 400$.",
    )

    # ofleet PDF Export API credentials (per-tenant)
    ofleet_username     = models.CharField(max_length=150, blank=True, verbose_name="ofleet اسم المستخدم", help_text="اسم المستخدم لـ API تصدير PDF من ofleet0.com")
    ofleet_password     = models.CharField(max_length=255, blank=True, verbose_name="ofleet كلمة المرور", help_text="كلمة المرور لـ API تصدير PDF من ofleet0.com")
    ofleet_split_by_make = models.BooleanField(
        default=True,
        verbose_name="تقسيم PDF حسب الماركة",
        help_text="عند التفعيل: يتم إنشاء ملف PDF منفصل لكل ماركة. عند الإيقاف: ملف PDF واحد يشمل جميع السيارات.",
    )

    auto_create_schema = True

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Only run image optimization on new uploads (not on programmatic field updates)
        update_fields = kwargs.get('update_fields')
        if not update_fields:
            if self.logo and getattr(self.logo, '_file', None) is not None:
                self.logo = optimize_image(self.logo, max_width=400, max_height=400, quality=85)
            if self.favicon and getattr(self.favicon, '_file', None) is not None:
                self.favicon = optimize_image(self.favicon, max_width=64, max_height=64, quality=90)
            if self.hero_image and getattr(self.hero_image, '_file', None) is not None:
                self.hero_image = optimize_image(self.hero_image, max_width=1920, max_height=1080, quality=82)
            if self.contact_person_photo and getattr(self.contact_person_photo, '_file', None) is not None:
                self.contact_person_photo = optimize_image(self.contact_person_photo, max_width=400, max_height=400, quality=85)
        super().save(*args, **kwargs)


class Domain(DomainMixin):
    pass


class GlobalExchangeRates(models.Model):
    """
    Singleton holding currency exchange rates shared by all tenants.
    Rates are expressed per 1 KRW. Use `GlobalExchangeRates.get_solo()`.
    """
    rate_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0.00067, verbose_name="سعر الدولار USD")
    rate_sar = models.DecimalField(max_digits=10, decimal_places=6, default=0.00250, verbose_name="سعر الريال SAR")
    rate_aed = models.DecimalField(max_digits=10, decimal_places=6, default=0.00272, verbose_name="سعر الدرهم AED")
    rate_eur = models.DecimalField(max_digits=10, decimal_places=6, default=0.00069, verbose_name="سعر اليورو EUR")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "أسعار صرف العملات (عام)"
        verbose_name_plural = "أسعار صرف العملات (عام)"

    def __str__(self):
        return f"Global rates (USD={self.rate_usd}, SAR={self.rate_sar}, AED={self.rate_aed}, EUR={self.rate_eur})"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        from django.core.cache import cache
        cache.delete("global_exchange_rates")

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get_solo(cls):
        from django.core.cache import cache
        cached = cache.get("global_exchange_rates")
        if cached:
            return cached
        obj, _ = cls.objects.get_or_create(pk=1)
        cache.set("global_exchange_rates", obj, 60 * 30)
        return obj


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

    def save(self, *args, **kwargs):
        if self.image and hasattr(self.image, 'file'):
            self.image = optimize_image(self.image, max_width=1920, max_height=1080, quality=82)
        super().save(*args, **kwargs)


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
