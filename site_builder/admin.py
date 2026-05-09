from django.contrib import admin
from django.db import OperationalError, ProgrammingError, connection

from .models import (
    FooterColumn,
    FooterLink,
    ListingConfig,
    NavLink,
    Page,
    PageSection,
)


def _is_tenant_schema():
    """site_builder models live in tenant schemas only — hide from the public/admin index."""
    return getattr(connection, "schema_name", "public") != "public"


class _TenantOnlyAdminMixin:
    def has_module_permission(self, request):
        return _is_tenant_schema() and super().has_module_permission(request)


class PageSectionInline(admin.StackedInline):
    model = PageSection
    extra = 0
    fields = (
        "type",
        "order",
        "is_visible",
        ("title", "title_en"),
        ("subtitle", "subtitle_en"),
        "body",
        "image",
        "config",
    )
    ordering = ("order",)


@admin.register(Page)
class PageAdmin(_TenantOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("title", "kind", "slug", "is_published", "show_in_nav", "nav_order")
    list_filter = ("kind", "is_published", "show_in_nav")
    search_fields = ("title", "title_en", "slug")
    prepopulated_fields = {"slug": ("title_en",)}
    inlines = [PageSectionInline]
    fieldsets = (
        (None, {"fields": ("kind", "title", "title_en", "slug", "meta_description")}),
        ("Visibility", {"fields": ("is_published", "show_in_nav", "nav_order")}),
    )


@admin.register(PageSection)
class PageSectionAdmin(_TenantOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("page", "type", "order", "is_visible", "title")
    list_filter = ("type", "is_visible", "page")
    list_editable = ("order", "is_visible")
    search_fields = ("title", "title_en", "body")


@admin.register(NavLink)
class NavLinkAdmin(_TenantOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("label", "parent", "order", "is_visible", "url", "page")
    list_filter = ("is_visible", "parent")
    list_editable = ("order", "is_visible")
    search_fields = ("label", "label_en", "url")
    autocomplete_fields = ("page", "parent")


class FooterLinkInline(admin.TabularInline):
    model = FooterLink
    extra = 0
    fields = ("label", "label_en", "url", "page", "order", "is_visible", "open_in_new_tab")
    autocomplete_fields = ("page",)


@admin.register(FooterColumn)
class FooterColumnAdmin(_TenantOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("title", "order", "is_visible")
    list_editable = ("order", "is_visible")
    search_fields = ("title", "title_en")
    inlines = [FooterLinkInline]


@admin.register(FooterLink)
class FooterLinkAdmin(_TenantOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("label", "column", "order", "is_visible", "url", "page")
    list_filter = ("column", "is_visible")
    list_editable = ("order", "is_visible")
    search_fields = ("label", "label_en", "url")
    autocomplete_fields = ("page", "column")


@admin.register(ListingConfig)
class ListingConfigAdmin(_TenantOnlyAdminMixin, admin.ModelAdmin):
    fieldsets = (
        ("Filter widgets", {
            "fields": (
                "show_search",
                "show_manufacturer",
                "show_model",
                "show_year_range",
                "show_price_range",
                "show_fuel",
                "show_transmission",
                "show_body_type",
                "show_color",
                "show_mileage_range",
            ),
        }),
        ("Defaults", {"fields": ("default_sort", "page_size")}),
    )

    def has_add_permission(self, request):
        # Singleton: only one row per tenant. Defensive against missing table
        # (public schema or pre-migration tenant).
        try:
            return not ListingConfig.objects.exists()
        except (ProgrammingError, OperationalError):
            return False

    def has_delete_permission(self, request, obj=None):
        return False
