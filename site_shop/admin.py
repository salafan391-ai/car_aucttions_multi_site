from django.contrib import admin

from .models import ShopItem, ShopItemImage


class ShopItemImageInline(admin.TabularInline):
    model = ShopItemImage
    extra = 1
    fields = ("image", "caption", "order")
    ordering = ("order",)


@admin.register(ShopItem)
class ShopItemAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "category", "brand", "part_number", "origin", "price", "currency", "condition", "in_stock", "is_featured", "created_at")
    list_filter = ("kind", "origin", "condition", "in_stock", "is_featured", "brand")
    list_editable = ("in_stock", "is_featured")
    search_fields = ("name", "brand", "category", "part_number", "part_number_norm", "fits_make", "fits_model")
    inlines = [ShopItemImageInline]
