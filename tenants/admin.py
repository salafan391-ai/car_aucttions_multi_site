from django.contrib import admin
from django_tenants.admin import TenantAdminMixin
from .models import Tenant, Domain

from cars.models import ApiCar,CarImage,Manufacturer,BodyType

@admin.register(ApiCar)
class ApiCarAdmin(admin.ModelAdmin):
    search_fields = ("manufacturer__name", "model__name", "car_id", "lot_number", "vin")

admin.site.register(CarImage)
admin.site.register(Manufacturer)
admin.site.register(BodyType)

@admin.register(Tenant)
class TenantAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("name", "schema_name", "primary_color", "created_at")
    fieldsets = (
        (None, {"fields": ("schema_name", "name")}),
        ("Branding", {"fields": ("logo", "favicon", "primary_color", "secondary_color", "accent_color")}),
        ("Footer", {"fields": ("footer_text", "footer_text_en")}),
        ("Business Info (عربي)", {"fields": ("about", "address", "city", "working_hours")}),
        ("Business Info (English)", {"fields": ("about_en", "address_en", "city_en", "working_hours_en")}),
        ("Contact", {"fields": ("phone", "phone2", "whatsapp", "email", "map_url")}),
        ("Contact Person", {"fields": ("contact_person_name", "contact_person_photo")}),
        ("Social Media", {"fields": ("instagram", "twitter", "facebook", "tiktok", "snapchat", "youtube"), "classes": ("collapse",)}),
        ("Email SMTP Settings", {"fields": ("email_host", "email_port", "email_username", "email_password", "email_use_tls", "email_from_name"), "classes": ("collapse",)}),
    )


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("domain", "tenant", "is_primary")
