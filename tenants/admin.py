from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import render
from django_tenants.admin import TenantAdminMixin
from django_tenants.utils import schema_context

from .models import Tenant, Domain, TenantPhoneNumber, TenantHeroImage, GlobalExchangeRates

from cars.models import CarImage, Manufacturer, BodyType


@admin.action(description="➕ إنشاء مستخدم مشرف (superuser) داخل الموقع المحدد")
def create_tenant_superuser(modeladmin, request, queryset):
    """Create a superuser inside one selected tenant's own schema.

    Shows an intermediate form (username / email / password), then creates the
    user in that tenant's auth_user table — not the public one.
    """
    if not request.user.is_superuser:
        modeladmin.message_user(request, "هذا الإجراء متاح لمشرفي المنصة فقط.", level=messages.ERROR)
        return
    if queryset.count() != 1:
        modeladmin.message_user(request, "اختر موقعاً واحداً فقط لإنشاء مشرف له.", level=messages.ERROR)
        return
    tenant = queryset.first()
    if tenant.schema_name == "public":
        modeladmin.message_user(request, "للنطاق العام استخدم إضافة مستخدم العادية في الأدمن.", level=messages.ERROR)
        return

    ctx = {
        "tenant": tenant, "queryset": queryset, "opts": modeladmin.model._meta,
        "title": f"إنشاء مشرف للموقع: {tenant.name}",
        "username": request.POST.get("username", ""), "email": request.POST.get("email", ""),
        "action_name": "create_tenant_superuser",
    }

    if request.POST.get("apply"):
        username = (request.POST.get("username") or "").strip()
        email = (request.POST.get("email") or "").strip()
        p1 = request.POST.get("password1") or ""
        p2 = request.POST.get("password2") or ""
        errors = []
        if not username:
            errors.append("اسم المستخدم مطلوب.")
        if p1 != p2:
            errors.append("كلمتا المرور غير متطابقتين.")
        try:
            validate_password(p1)
        except ValidationError as e:
            errors.extend(e.messages)

        if not errors:
            with schema_context(tenant.schema_name):
                User = get_user_model()
                if User.objects.filter(username=username).exists():
                    errors.append("اسم المستخدم موجود مسبقاً في هذا الموقع.")
                else:
                    User.objects.create_superuser(username=username, email=email, password=p1)

        if errors:
            for e in errors:
                modeladmin.message_user(request, e, level=messages.ERROR)
        else:
            modeladmin.message_user(
                request, f"تم إنشاء المشرف «{username}» داخل موقع «{tenant.name}».",
                level=messages.SUCCESS)
            return None  # back to the changelist

    return render(request, "admin/create_tenant_superuser.html", ctx)

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
    list_display = ("name", "schema_name", "is_active", "primary_color", "created_at")
    list_editable = ("is_active",)
    list_filter = ("is_active",)
    actions = ["create_tenant_superuser"]
    inlines = [TenantPhoneNumberInline, TenantHeroImageInline]

    def create_tenant_superuser(self, request, queryset):
        return create_tenant_superuser(self, request, queryset)
    create_tenant_superuser.short_description = "➕ إنشاء مستخدم مشرف (superuser) داخل الموقع المحدد"
    fieldsets = (
        (None, {"fields": ("schema_name", "name", "is_active", "eid_is_active")}),
        ("Branding", {"fields": ("logo", "favicon", "hero_image", "show_hero", "show_watermark", "show_encar", "show_auctions", "show_site_cars", "show_parts", "show_accessories", "landing_is_active", "landing_design", "template_theme", "site_font", "theme", "primary_color", "secondary_color", "accent_color", "body_bg_color", "car_display")}),
        ("Announcement ticker", {"fields": ("ticker_enabled", "ticker_text", "ticker_color")}),
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
