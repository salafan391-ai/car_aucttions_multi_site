from django.contrib import admin

from .models import ShopItem, ShopItemImage, ShopRequest


@admin.register(ShopRequest)
class ShopRequestAdmin(admin.ModelAdmin):
    list_display = ("kind", "phone", "email", "car_vin", "is_handled", "created_at")
    list_filter = ("kind", "is_handled")
    list_editable = ("is_handled",)
    search_fields = ("phone", "email", "car_vin", "car_description", "item_description")
    readonly_fields = ("created_at",)


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
