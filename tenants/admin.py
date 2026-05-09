from django.contrib import admin
from django_tenants.admin import TenantAdminMixin
from .models import Tenant, Domain, TenantPhoneNumber, TenantHeroImage, GlobalExchangeRates

from cars.models import CarImage, Manufacturer, BodyType

admin.site.register(CarImage)
admin.site.register(Manufacturer)
admin.site.register(BodyType)


class TenantPhoneNumberInline(admin.TabularInline):
    model = TenantPhoneNumber
    extra = 1
    fields = ('phone_number', 'phone_type', 'label', 'is_primary', 'is_active', 'order')
    ordering = ['order', '-is_primary']


class TenantHeroImageInline(admin.TabularInline):
    model = TenantHeroImage
    extra = 1
    fields = ('image', 'order')
    ordering = ['order']


@admin.register(Tenant)
class TenantAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("name", "schema_name", "primary_color", "created_at")
    inlines = [TenantPhoneNumberInline, TenantHeroImageInline]
    fieldsets = (
        (None, {"fields": ("schema_name", "name", "eid_is_active")}),
        ("Branding", {"fields": ("logo", "favicon", "hero_image", "show_hero", "show_watermark", "landing_is_active", "landing_design", "template_theme", "theme", "primary_color", "secondary_color", "accent_color", "body_bg_color", "car_display")}),
        ("Footer", {"fields": ("footer_text", "footer_text_en")}),
        ("Business Info (عربي)", {"fields": ("tagline", "about", "address", "city", "working_hours")}),
        ("Business Info (English)", {"fields": ("tagline_en", "about_en", "address_en", "city_en", "working_hours_en")}),
        ("Contact", {"fields": ("phone", "phone2", "whatsapp", "email", "map_url"), "description": "ملاحظة: يمكنك إدارة أرقام متعددة في قسم 'أرقام الهواتف' أسفل الصفحة"}),
        ("Contact Person", {"fields": ("contact_person_name", "contact_person_photo")}),
        ("Social Media", {"fields": ("instagram", "twitter", "facebook", "tiktok", "snapchat", "youtube"), "classes": ("collapse",)}),
        ("Email SMTP Settings", {"fields": ("email_host", "email_port", "email_username", "email_password", "email_use_tls", "email_from_name"), "classes": ("collapse",)}),
        ("ofleet PDF Export API", {"fields": ("ofleet_username", "ofleet_password", "ofleet_split_by_make"), "classes": ("collapse",), "description": "بيانات تسجيل الدخول الخاصة بهذا الموقع لـ API تصدير PDF من ofleet0.com"}),
    )


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("domain", "tenant", "is_primary")


@admin.register(GlobalExchangeRates)
class GlobalExchangeRatesAdmin(admin.ModelAdmin):
    list_display = ("rate_usd", "rate_sar", "rate_aed", "rate_eur", "updated_at")

    def has_add_permission(self, request):
        return not GlobalExchangeRates.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
