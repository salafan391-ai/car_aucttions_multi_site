from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html
from django_tenants.admin import TenantAdminMixin
from django_tenants.utils import schema_context

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
    list_display = ("name", "schema_name", "is_active", "create_superuser_button", "primary_color", "created_at")
    list_editable = ("is_active",)
    list_filter = ("is_active",)
    inlines = [TenantPhoneNumberInline, TenantHeroImageInline]

    # ── Create a superuser inside a tenant's own schema ──
    def get_urls(self):
        return [
            path("<int:pk>/create-superuser/", self.admin_site.admin_view(self.create_superuser_view),
                 name="tenants_tenant_create_superuser"),
        ] + super().get_urls()

    @admin.display(description="مستخدم مشرف")
    def create_superuser_button(self, obj):
        if obj.schema_name == "public":
            return "—"
        url = reverse("admin:tenants_tenant_create_superuser", args=[obj.pk])
        return format_html('<a class="button" href="{}" style="white-space:nowrap">➕ إنشاء مشرف</a>', url)

    def create_superuser_view(self, request, pk):
        """A real admin page to create a superuser inside one tenant's schema."""
        if not request.user.is_superuser:
            self.message_user(request, "متاح لمشرفي المنصة فقط.", level=messages.ERROR)
            return redirect("admin:tenants_tenant_changelist")
        tenant = get_object_or_404(Tenant, pk=pk)
        if tenant.schema_name == "public":
            self.message_user(request, "للنطاق العام استخدم إضافة مستخدم العادية في الأدمن.", level=messages.ERROR)
            return redirect("admin:tenants_tenant_changelist")

        if request.method == "POST":
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
                    messages.error(request, e)
            else:
                self.message_user(
                    request, f"تم إنشاء المشرف «{username}» داخل موقع «{tenant.name}».",
                    level=messages.SUCCESS)
                return redirect("admin:tenants_tenant_changelist")

        ctx = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta, "tenant": tenant,
            "title": f"إنشاء مشرف للموقع: {tenant.name}",
            "username": request.POST.get("username", ""), "email": request.POST.get("email", ""),
        }
        return render(request, "admin/create_tenant_superuser.html", ctx)

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
