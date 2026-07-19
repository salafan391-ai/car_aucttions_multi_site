from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html
from django_tenants.admin import TenantAdminMixin
from django_tenants.utils import schema_context

from .models import Tenant, Domain, TenantPhoneNumber, TenantHeroImage, TenantWorkStep, TenantSalesPerson, GlobalExchangeRates

from cars.models import CarImage, Manufacturer, BodyType


admin.site.register(CarImage)
admin.site.register(Manufacturer)
admin.site.register(BodyType)


class TenantPhoneNumberInline(admin.TabularInline):
    model = TenantPhoneNumber
    extra = 1
    fields = ('phone_number', 'phone_type', 'label', 'is_primary', 'is_active', 'order')
    ordering = ['order', '-is_primary']


class TenantSalesPersonInline(admin.TabularInline):
    model = TenantSalesPerson
    extra = 1
    fields = ('name', 'role', 'photo', 'whatsapp', 'phone', 'is_active', 'order')
    ordering = ['order']


class TenantHeroImageInline(admin.TabularInline):
    model = TenantHeroImage
    extra = 1
    fields = ('image', 'title', 'description', 'link_url', 'order')
    ordering = ['order']


class TenantWorkStepInline(admin.TabularInline):
    model = TenantWorkStep
    extra = 1
    fields = ('order', 'icon', 'title', 'description', 'is_active')
    ordering = ['order']


class TenantAdminForm(forms.ModelForm):
    """Checkbox picker for which themes a tenant's admins may choose in their
    dashboard. Stored in the dashboard_themes JSON list; empty = default set
    (default/glassy/modern/market/export)."""
    dashboard_themes = forms.MultipleChoiceField(
        required=False,
        choices=[(k, f"{l} — {d}") for k, l, d in Tenant.THEME_CATALOG],
        widget=forms.CheckboxSelectMultiple,
        label="الثيمات المتاحة في لوحة التحكم",
        help_text="حدد الثيمات التي تظهر لأدمن هذا الموقع في صفحة الإعدادات. اتركها كلها بدون تحديد لاستخدام المجموعة الافتراضية.",
    )
    enabled_markets = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="الأسواق المفعّلة",
        help_text="فئات الأسواق التي تظهر كتبويب مستقل لهذا الموقع (مثل السوق الياباني). اتركها فارغة لإخفاء كل الأسواق.",
    )

    class Meta:
        model = Tenant
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Market choices come from cars.Category rows flagged as market tabs, so
        # adding a new market in the Category admin makes it selectable here — no
        # code change needed.
        try:
            from cars.models import Category
            self.fields['enabled_markets'].choices = [
                (c.name, c.label_ar or c.name)
                for c in Category.objects.filter(is_market_tab=True).order_by('tab_order', 'name')
                if c.name
            ]
        except Exception:
            self.fields['enabled_markets'].choices = []

    def clean_dashboard_themes(self):
        return list(self.cleaned_data.get("dashboard_themes") or [])

    def clean_enabled_markets(self):
        return list(self.cleaned_data.get("enabled_markets") or [])


@admin.register(Tenant)
class TenantAdmin(TenantAdminMixin, admin.ModelAdmin):
    form = TenantAdminForm
    list_display = ("name", "schema_name", "is_active", "create_superuser_button", "primary_color", "dashboard_themes_display", "telegram_display", "created_at")

    @admin.display(description="ثيمات اللوحة")
    def dashboard_themes_display(self, obj):
        return "، ".join(obj.dashboard_themes) if obj.dashboard_themes else "(الافتراضية)"

    @admin.display(description="تيليجرام (سلة الروابط)")
    def telegram_display(self, obj):
        if not obj.telegram_chat_id:
            return format_html('<span style="color:#9ca3af;">{}</span>', 'غير متصل')
        who = obj.telegram_chat_name or "؟"
        return format_html('<b>{}</b><br><code style="font-size:11px;">{}</code>', who, obj.telegram_chat_id)

    list_editable = ("is_active",)
    list_filter = ("is_active",)
    inlines = [TenantPhoneNumberInline, TenantSalesPersonInline, TenantHeroImageInline, TenantWorkStepInline]

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
        ("الأسواق (Markets)", {"fields": ("enabled_markets",), "description": "التبويبات المستقلة للأسواق (مثل السوق الياباني). تُدار الفئات نفسها من قسم Categories."}),
        ("المزادات (Auctions)", {"fields": ("auction_grace_hours",), "description": "سيارات المزاد مشتركة بين كل المواقع — هذه المهلة تغيّر وقت اختفائها على هذا الموقع فقط."}),
        ("Branding", {"fields": ("logo", "favicon", "hero_image", "show_hero", "show_watermark", "show_encar", "show_auctions", "show_site_cars", "show_parts", "show_accessories", "landing_is_active", "landing_design", "template_theme", "dashboard_themes", "site_font", "theme", "primary_color", "secondary_color", "accent_color", "body_bg_color", "car_display")}),
        ("Announcement ticker", {"fields": ("ticker_enabled", "ticker_text", "ticker_color")}),
        ("How we work", {"fields": ("show_how_we_work", "how_we_work_title")}),
        ("Footer", {"fields": ("footer_text", "footer_text_en")}),
        ("Business Info (عربي)", {"fields": ("tagline", "about", "address", "city", "working_hours")}),
        ("Business Info (English)", {"fields": ("tagline_en", "about_en", "address_en", "city_en", "working_hours_en")}),
        ("Contact", {"fields": ("phone", "phone2", "whatsapp", "email", "map_url"), "description": "ملاحظة: يمكنك إدارة أرقام متعددة في قسم 'أرقام الهواتف' أسفل الصفحة"}),
        ("Contact Person", {"fields": ("contact_person_name", "contact_person_photo")}),
        ("Commercial Registration", {"fields": ("commercial_registration", "cr_barcode")}),
        ("Social Media", {"fields": ("instagram", "twitter", "facebook", "tiktok", "snapchat", "youtube", "telegram", "telegram_username", "whatsapp_channel"), "classes": ("collapse",)}),
        ("Telegram bot (سلة الروابط)", {"fields": ("telegram_chat_id", "telegram_chat_name"), "classes": ("collapse",), "description": "الحساب المرتبط بـ ofleet0_bot الذي تصله روابط السيارات من سلة الروابط. امسح الحقلين لفصل الربط."}),
        ("Email SMTP Settings", {"fields": ("email_host", "email_port", "email_username", "email_password", "email_use_tls", "email_from_name"), "classes": ("collapse",)}),
        ("ofleet PDF Export API", {"fields": ("ofleet_username", "ofleet_password", "ofleet_split_by_make"), "classes": ("collapse",), "description": "بيانات تسجيل الدخول الخاصة بهذا الموقع لـ API تصدير PDF من ofleet0.com"}),
    )


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("domain", "tenant", "is_primary", "current_ip")
    actions = ("activate_on_vps",)

    @admin.display(description="Current IP")
    def current_ip(self, obj):
        """Live A-record the domain resolves to (cached 5 min). Green ✓ VPS when
        it points at this box, orange when it's still on Railway/Cloudflare."""
        import os
        import socket
        from django.core.cache import cache
        from django.utils.html import format_html
        vps = os.environ.get("VPS_IP") or "142.132.232.37"
        key = f"domain_ip:{obj.domain}"
        ip = cache.get(key)
        if ip is None:
            try:
                ip = socket.gethostbyname(obj.domain)
            except Exception:
                ip = ""
            cache.set(key, ip, 300)
        if ip == vps:
            return format_html('<b style="color:#0a8a0a">✓ VPS</b> {}', ip)
        if not ip:
            return format_html('<span style="color:#999">{}</span>', '—')
        return format_html('<span style="color:#c60">{}</span>', ip)

    @admin.action(description="Activate on VPS (point Cloudflare DNS here)")
    def activate_on_vps(self, request, queryset):
        """Set each selected domain's Cloudflare A record to the VPS (grey-cloud).
        Caddy then issues the TLS cert on-demand on the first HTTPS hit."""
        from django.contrib import messages
        from .cloudflare import point_domain_to_vps, CloudflareError
        for d in queryset:
            try:
                msg = point_domain_to_vps(d.domain)
                self.message_user(request, f"✓ {msg}", level=messages.SUCCESS)
            except CloudflareError as e:
                self.message_user(request, f"✗ {d.domain}: {e}", level=messages.ERROR)
            except Exception as e:  # network/unexpected — surface, don't 500
                self.message_user(request, f"✗ {d.domain}: {e}", level=messages.ERROR)


@admin.register(GlobalExchangeRates)
class GlobalExchangeRatesAdmin(admin.ModelAdmin):
    list_display = ("rate_usd", "rate_sar", "rate_aed", "rate_eur", "updated_at")

    def has_add_permission(self, request):
        return not GlobalExchangeRates.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
