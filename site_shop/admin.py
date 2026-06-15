from django.contrib import admin

from .models import ShopItem, ShopItemImage


class ShopItemImageInline(admin.TabularInline):
    model = ShopItemImage
    extra = 1
    fields = ("image", "caption", "order")
    ordering = ("order",)


@admin.register(ShopItem)
class ShopItemAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "category", "brand", "price", "currency", "condition", "in_stock", "is_featured", "created_at")
    list_filter = ("kind", "condition", "in_stock", "is_featured", "brand")
    list_editable = ("in_stock", "is_featured")
    search_fields = ("name", "brand", "category", "fits_make", "fits_model")
    inlines = [ShopItemImageInline]
