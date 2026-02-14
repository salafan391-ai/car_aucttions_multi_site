from django.contrib import admin
from .models import Manufacturer, CarModel, CarBadge, CarColor, BodyType, Wishlist

@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ('user', 'car', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'car__title')
