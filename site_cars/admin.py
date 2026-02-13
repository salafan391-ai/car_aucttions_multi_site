from django.contrib import admin
from .models import SiteCar, SiteCarImage, SiteOrder, SiteBill, SiteRating, SiteQuestion, SiteSoldCar, SiteMessage, SiteEmailLog


class SiteCarImageInline(admin.TabularInline):
    model = SiteCarImage
    extra = 3
    fields = ("image", "caption", "order")


@admin.register(SiteCar)
class SiteCarAdmin(admin.ModelAdmin):
    list_display = ("title", "manufacturer", "model", "year", "price", "status", "is_featured", "created_at")
    list_filter = ("status", "is_featured", "manufacturer", "year")
    search_fields = ("title", "manufacturer", "model")
    list_editable = ("status", "is_featured")
    inlines = [SiteCarImageInline]
    fieldsets = (
        (None, {"fields": ("title", "description")}),
        ("المواصفات", {"fields": ("manufacturer", "model", "year", "color", "mileage", "transmission", "fuel", "body_type", "engine", "drive_wheel")}),
        ("السعر والحالة", {"fields": ("price", "status", "is_featured")}),
        ("الصورة الرئيسية", {"fields": ("image",)}),
    )


class SiteBillInline(admin.TabularInline):
    model = SiteBill
    extra = 0


@admin.register(SiteOrder)
class SiteOrderAdmin(admin.ModelAdmin):
    list_display = ("pk", "user", "car", "offer_price", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("car__title", "user__username", "notes")
    list_editable = ("status",)
    autocomplete_fields = ("car",)
    inlines = [SiteBillInline]
    fieldsets = (
        (None, {"fields": ("user", "car")}),
        ("التفاصيل", {"fields": ("offer_price", "status", "notes", "admin_notes")}),
        ("التواريخ", {"fields": ("completed_at",)}),
    )

    def save_model(self, request, obj, form, change):
        if change and 'status' in form.changed_data and obj.status == 'completed':
            from django.utils import timezone
            obj.completed_at = timezone.now()
            super().save_model(request, obj, form, change)
            car = obj.car
            car.status = 'sold'
            car.save(update_fields=['status'])
            SiteSoldCar.objects.get_or_create(
                car=car,
                defaults={
                    'buyer': obj.user,
                    'sale_price': obj.offer_price,
                    'original_price': car.price,
                },
            )
            from .email_utils import send_order_status_email
            send_order_status_email(obj)
        elif change and 'status' in form.changed_data:
            super().save_model(request, obj, form, change)
            from .email_utils import send_order_status_email
            send_order_status_email(obj)
        else:
            super().save_model(request, obj, form, change)


@admin.register(SiteBill)
class SiteBillAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "order", "price", "date", "is_paid")
    list_filter = ("is_paid",)
    list_editable = ("is_paid",)
    search_fields = ("receipt_number",)


@admin.register(SiteRating)
class SiteRatingAdmin(admin.ModelAdmin):
    list_display = ("user", "car", "rating", "created_at")
    list_filter = ("rating",)
    search_fields = ("car__title", "user__username", "comment")
    autocomplete_fields = ("car",)


@admin.register(SiteQuestion)
class SiteQuestionAdmin(admin.ModelAdmin):
    list_display = ("user", "car", "question_short", "is_answered", "created_at")
    list_filter = ("is_answered",)
    list_editable = ("is_answered",)
    search_fields = ("question", "user__username", "car__title")
    autocomplete_fields = ("car",)

    def question_short(self, obj):
        return obj.question[:60] + "..." if len(obj.question) > 60 else obj.question
    question_short.short_description = "السؤال"


@admin.register(SiteSoldCar)
class SiteSoldCarAdmin(admin.ModelAdmin):
    list_display = ("car", "buyer", "sale_price", "original_price", "sold_at")
    search_fields = ("car__title", "buyer__username")
    autocomplete_fields = ("car",)
    fieldsets = (
        (None, {"fields": ("car",)}),
        ("البيع", {"fields": ("buyer", "sale_price", "original_price", "notes")}),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        car = obj.car
        if car.status != 'sold':
            car.status = 'sold'
            car.save(update_fields=['status'])


@admin.register(SiteMessage)
class SiteMessageAdmin(admin.ModelAdmin):
    list_display = ("sender", "recipient", "subject", "is_read", "created_at")
    list_filter = ("is_read",)
    search_fields = ("subject", "body", "sender__username", "recipient__username")
    list_editable = ("is_read",)


@admin.register(SiteEmailLog)
class SiteEmailLogAdmin(admin.ModelAdmin):
    list_display = ("email_type", "recipient_email", "subject", "status", "created_at")
    list_filter = ("status", "email_type")
    search_fields = ("recipient_email", "subject")
    readonly_fields = ("recipient_email", "recipient_user", "subject", "body", "email_type", "status", "error_message", "created_at")
