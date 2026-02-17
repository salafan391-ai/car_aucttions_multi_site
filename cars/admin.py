from django.contrib import admin
from .models import Manufacturer, CarModel, CarBadge, CarColor, BodyType, Wishlist, Post, PostImage, PostLike, PostComment

class PostImageInline(admin.TabularInline):
    model = PostImage
    extra = 1
    fields = ('image', 'caption', 'order')

@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'is_published', 'views_count', 'likes_count', 'comments_count', 'created_at')
    list_filter = ('is_published', 'created_at', 'author')
    search_fields = ('title', 'title_ar', 'content', 'content_ar')
    inlines = [PostImageInline]
    readonly_fields = ('views_count', 'created_at', 'updated_at')
    
    fieldsets = (
        ('معلومات أساسية', {
            'fields': ('title', 'title_ar', 'author', 'is_published')
        }),
        ('المحتوى', {
            'fields': ('content', 'content_ar', 'video_url')
        }),
        ('إحصائيات', {
            'fields': ('views_count', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not change:  # If creating new post
            obj.author = request.user
        super().save_model(request, obj, form, change)

@admin.register(PostImage)
class PostImageAdmin(admin.ModelAdmin):
    list_display = ('post', 'caption', 'order', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('post__title', 'caption')

@admin.register(PostLike)
class PostLikeAdmin(admin.ModelAdmin):
    list_display = ('post', 'user', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('post__title', 'user__username')

@admin.register(PostComment)
class PostCommentAdmin(admin.ModelAdmin):
    list_display = ('post', 'user', 'comment_preview', 'is_approved', 'created_at')
    list_filter = ('is_approved', 'created_at')
    search_fields = ('post__title', 'user__username', 'comment')
    actions = ['approve_comments', 'disapprove_comments']
    
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
