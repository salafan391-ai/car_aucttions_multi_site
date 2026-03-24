from django.contrib import admin
from django.contrib import messages
from django.db import connection
from django.http import HttpResponse
from django.utils.html import format_html
from .models import Manufacturer, CarModel, CarBadge, CarColor, BodyType, Wishlist, Post, PostImage, PostLike, PostComment, Category, CarRequest, Contact, ApiCar, PdfExport
from .export_service import start_export


@admin.register(ApiCar)
class ApiCarAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'manufacturer', 'year', 'price', 'auction_date', 'created_at')
    list_filter = ('category', 'manufacturer', 'year')
    search_fields = ('title', 'manufacturer__name', 'model__name', 'car_id', 'lot_number', 'vin')
    actions = ['delete_by_category_auction', 'delete_by_category_car', 'export_pdf_bulk']

    def delete_by_category_auction(self, request, queryset):
        qs = ApiCar.objects.filter(category__name='auction')
        count = qs.count()
        qs.delete()
        self.message_user(request, f'تم حذف {count} سيارة من فئة "مزاد".', messages.SUCCESS)
    delete_by_category_auction.short_description = '🗑️ حذف جميع سيارات فئة: مزاد (auction)'

    def delete_by_category_car(self, request, queryset):
        qs = ApiCar.objects.filter(category__name='car')
        count = qs.count()
        qs.delete()
        self.message_user(request, f'تم حذف {count} سيارة من فئة "سيارة".', messages.SUCCESS)
    delete_by_category_car.short_description = '🗑️ حذف جميع سيارات فئة: سيارة (car)'

    def export_pdf_bulk(self, request, queryset):
        """
        Submit an export job to ofleet. ofleet calls our /webhook/ofleet/ endpoint
        when the job is done — no background threads, no polling.
        """
        cars = list(queryset.values_list('entry', 'auction_name'))
        entries_by_auction = {}
        for entry, auction_name in cars:
            if not entry:
                continue
            entries_by_auction.setdefault(auction_name or 'unknown', []).append(entry)

        if not entries_by_auction:
            self.message_user(request, "لا توجد قيم entry للسيارات المحددة.", messages.WARNING)
            return

        if len(entries_by_auction) > 1:
            self.message_user(
                request,
                f"تم تحديد {len(entries_by_auction)} مزادات مختلفة — سيتم تصدير المزاد الأول فقط: "
                f"«{list(entries_by_auction.keys())[0]}».",
                messages.WARNING,
            )

        auction_name, entries = next(iter(entries_by_auction.items()))

        # Build the webhook URL for this specific tenant.
        # Using the tenant's own primary domain ensures django-tenants activates
        # the correct schema when ofleet calls the webhook back.
        from django.conf import settings as _s
        _base = getattr(_s, 'WEBHOOK_BASE_URL', '').rstrip('/')
        if not _base:
            try:
                _domain = connection.tenant.get_primary_domain()
                _base = f"https://{_domain.domain}"
            except Exception:
                _base = request.build_absolute_uri('/').rstrip('/')
        webhook_url = f"{_base}/webhook/ofleet/"

        # 2. Submit the job to ofleet (fast — just auth + POST, no polling)
        try:
            _token, _job_id = start_export(entries, auction_name, webhook_url)
        except ValueError as e:
            self.message_user(request, f"خطأ في الإعدادات: {e}", messages.ERROR)
            return
        except Exception as e:
            self.message_user(request, f"فشل بدء التصدير: {e}", messages.ERROR)
            return

        # 3. Create a PdfExport record (status=pending) — webhook will update it
        schema = getattr(connection, 'schema_name', '')
        PdfExport.objects.create(
            auction_name=auction_name,
            schema_name=schema,
            entry_count=len(entries),
            status=PdfExport.STATUS_PENDING,
        )

        self.message_user(
            request,
            f"تم إرسال طلب تصدير PDF للمزاد «{auction_name}» ({len(entries)} سيارة). "
            f"ستجد الملف جاهزاً في قائمة «تصديرات PDF» خلال لحظات.",
            messages.SUCCESS,
        )

    export_pdf_bulk.short_description = '📄 تصدير PDF للسيارات المحددة عبر ofleet'


@admin.register(PdfExport)
class PdfExportAdmin(admin.ModelAdmin):
    list_display  = ('auction_name', 'make_name', 'schema_name', 'entry_count', 'status_badge', 'download_link', 'created_at')
    list_filter   = ('status', 'schema_name', 'created_at')
    search_fields = ('auction_name', 'make_name', 'schema_name')
    readonly_fields = ('auction_name', 'make_name', 'schema_name', 'entry_count', 'status', 'pdf_file', 'error_detail', 'created_at')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def status_badge(self, obj):
        colors = {
            PdfExport.STATUS_PENDING:  ('#f59e0b', '⏳ جاري الإعداد'),
            PdfExport.STATUS_COMPLETE: ('#16a34a', '✅ جاهز'),
            PdfExport.STATUS_FAILED:   ('#dc2626', '❌ فشل'),
        }
        color, label = colors.get(obj.status, ('#6b7280', obj.status))
        return format_html(
            '<span style="color:{};font-weight:bold">{}</span>', color, label
        )
    status_badge.short_description = 'الحالة'

    def download_link(self, obj):
        if obj.status == PdfExport.STATUS_COMPLETE and obj.pdf_file:
            return format_html(
                '<a href="{}" target="_blank" style="'
                'background:#1d6fa4;color:#fff;padding:3px 10px;'
                'border-radius:4px;text-decoration:none;font-size:12px">'
                '⬇ تحميل PDF</a>',
                obj.pdf_file.url,
            )
        if obj.status == PdfExport.STATUS_FAILED:
            return format_html('<span style="color:#dc2626;font-size:11px">{}</span>', obj.error_detail[:80])
        return '—'
    download_link.short_description = 'تحميل'

class PostImageInline(admin.TabularInline):
    model = PostImage
    extra = 1
    fields = ('image', 'caption', 'order')

@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'tenant', 'is_published', 'views_count', 'likes_count', 'comments_count', 'created_at')
    list_filter = ('is_published', 'created_at', 'author', 'tenant')
    search_fields = ('title', 'title_ar', 'content', 'content_ar')
    inlines = [PostImageInline]
    readonly_fields = ('views_count', 'created_at', 'updated_at')
    
    fieldsets = (
        ('معلومات أساسية', {
            'fields': ('title', 'title_ar', 'author', 'tenant', 'is_published')
        }),
        ('المحتوى', {
            'fields': ('content', 'content_ar', 'video_url')
        }),
        ('إحصائيات', {
            'fields': ('views_count', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        """Filter posts by current tenant"""
        qs = super().get_queryset(request)
        tenant = getattr(connection, 'tenant', None)
        if tenant and connection.schema_name != 'public':
            return qs.filter(tenant=tenant)
        return qs
    
    def save_model(self, request, obj, form, change):
        if not change:  # If creating new post
            obj.author = request.user
            # Auto-set tenant
            tenant = getattr(connection, 'tenant', None)
            if tenant and connection.schema_name != 'public':
                obj.tenant = tenant
        super().save_model(request, obj, form, change)

@admin.register(PostImage)
class PostImageAdmin(admin.ModelAdmin):
    list_display = ('post', 'caption', 'order', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('post__title', 'caption')
    
    def get_queryset(self, request):
        """Filter post images by current tenant through post"""
        qs = super().get_queryset(request)
        tenant = getattr(connection, 'tenant', None)
        if tenant and connection.schema_name != 'public':
            return qs.filter(post__tenant=tenant)
        return qs

@admin.register(PostLike)
class PostLikeAdmin(admin.ModelAdmin):
    list_display = ('post', 'user', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('post__title', 'user__username')
    
    def get_queryset(self, request):
        """Filter post likes by current tenant through post"""
        qs = super().get_queryset(request)
        tenant = getattr(connection, 'tenant', None)
        if tenant and connection.schema_name != 'public':
            return qs.filter(post__tenant=tenant)
        return qs

@admin.register(PostComment)
class PostCommentAdmin(admin.ModelAdmin):
    list_display = ('post', 'user', 'comment_preview', 'is_approved', 'created_at')
    list_filter = ('is_approved', 'created_at')
    search_fields = ('post__title', 'user__username', 'comment')
    actions = ['approve_comments', 'disapprove_comments']
    
    def get_queryset(self, request):
        """Filter post comments by current tenant through post"""
        qs = super().get_queryset(request)
        tenant = getattr(connection, 'tenant', None)
        if tenant and connection.schema_name != 'public':
            return qs.filter(post__tenant=tenant)
        return qs
    
    def comment_preview(self, obj):
        return obj.comment[:50] + '...' if len(obj.comment) > 50 else obj.comment
    comment_preview.short_description = 'التعليق'
    
    def approve_comments(self, request, queryset):
        queryset.update(is_approved=True)
    approve_comments.short_description = 'الموافقة على التعليقات المحددة'
    
    def disapprove_comments(self, request, queryset):
        queryset.update(is_approved=False)
    disapprove_comments.short_description = 'إلغاء الموافقة على التعليقات المحددة'

@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ('user', 'car', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'car__title')


@admin.register(CarRequest)
class CarRequestAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'brand', 'model', 'year', 'city', 'status', 'is_read', 'created_at')
    list_filter = ('status', 'is_read', 'created_at')
    search_fields = ('name', 'phone', 'brand', 'model', 'city')
    list_editable = ('status', 'is_read')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-created_at',)

    fieldsets = (
        ('معلومات العميل', {
            'fields': ('name', 'phone', 'city')
        }),
        ('تفاصيل السيارة المطلوبة', {
            'fields': ('brand', 'model', 'year', 'colors', 'fuel', 'details')
        }),
        ('حالة الطلب', {
            'fields': ('status', 'is_read', 'admin_notes')
        }),
        ('التواريخ', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Mark unread count in the title
        return qs

    def changelist_view(self, request, extra_context=None):
        # Mark as read when admin opens the list
        extra_context = extra_context or {}
        extra_context['unread_count'] = CarRequest.objects.filter(is_read=False).count()
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'message_preview', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('name', 'email', 'phone', 'message')
    list_editable = ('is_read',)
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)

    def message_preview(self, obj):
        return obj.message[:60] + '...' if len(obj.message) > 60 else obj.message
    message_preview.short_description = 'الرسالة'


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'car_count')

    def car_count(self, obj):
        return ApiCar.objects.filter(category=obj).count()
    car_count.short_description = 'عدد السيارات'

admin.site.register(CarColor)



admin.site.register(CarModel)