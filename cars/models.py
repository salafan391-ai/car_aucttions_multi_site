from django.db import models
from django.conf import settings





class Upload(models.Model):
    file = models.FileField(upload_to='uploads/')
    created_at = models.DateTimeField(auto_now_add=True)



class Category(models.Model):
    name = models.CharField(max_length=100,blank=True,null=True)
    def __str__(self):
        return self.name

class Manufacturer(models.Model):
    name = models.CharField(max_length=100)
    name_ar = models.CharField(max_length=100, null=True, blank=True, verbose_name="الاسم بالعربي")
    country = models.CharField(max_length=100,null=True,blank=True)
    logo = models.CharField(max_length=255,null=True,blank=True)
    
    def __str__(self):
        return self.name

class CarModel(models.Model):
    name = models.CharField(max_length=100)
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.CASCADE)
    
    def __str__(self):
        return self.name

class CarBadge(models.Model):
    name = models.CharField(max_length=100,blank=True,null=True)
    model = models.ForeignKey(CarModel, on_delete=models.CASCADE)
    def __str__(self):
        return self.name

class CarColor(models.Model):
    name = models.CharField(max_length=100,blank=True,null=True)
    def __str__(self):
        return self.name


class CarSeatColor(models.Model):
    name = models.CharField(max_length=100,blank=True,null=True)
    def __str__(self):
        return self.name



class BodyType(models.Model):
    name = models.CharField(max_length=100,blank=True,null=True)
    name_ar = models.CharField(max_length=100,blank=True,null=True)
    def __str__(self):
        return self.name

class Wishlist(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_index=True)
    car = models.ForeignKey('ApiCar', on_delete=models.CASCADE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        unique_together = ['user', 'car']
        indexes = [
            models.Index(fields=['user', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.car.title}"

class ApiCar(models.Model):
    STATUS_CHOICES = [
        ('available', 'متاح'),
        ('sold', 'تم البيع'),
        ('pending', 'قيد الانتظار'),
    ]
    car_id = models.CharField(max_length=20, unique=True, db_index=True)
    title = models.CharField(max_length=100, db_index=True)
    image = models.CharField(max_length=255, null=True, blank=True)
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.CASCADE, db_index=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, blank=True, null=True, db_index=True)
    auction_date = models.DateTimeField(null=True, blank=True, db_index=True)
    auction_name = models.CharField(max_length=100,null=True,blank=True)
    vin = models.CharField(max_length=100,null=True,blank=True)
    lot_number = models.CharField(max_length=100, unique=True, db_index=True)
    model = models.ForeignKey(CarModel, on_delete=models.CASCADE, db_index=True)
    year = models.IntegerField(db_index=True)
    badge = models.ForeignKey(CarBadge, on_delete=models.CASCADE, db_index=True)
    color = models.ForeignKey(CarColor, on_delete=models.CASCADE, db_index=True)
    seat_color = models.ForeignKey(CarSeatColor, on_delete=models.CASCADE,blank=True,null=True)
    seat_count = models.CharField(max_length=100,blank=True,null=True)
    transmission = models.CharField(max_length=100,blank=True,null=True, db_index=True)
    engine = models.CharField(max_length=100,blank=True,null=True)
    condition = models.CharField(max_length=100,blank=True,null=True)
    body = models.ForeignKey(BodyType, on_delete=models.CASCADE,blank=True,null=True, db_index=True)
    power = models.IntegerField(null=True,blank=True)
    price = models.BigIntegerField(db_index=True)  # Changed to BigIntegerField for large prices
    mileage = models.BigIntegerField(db_index=True)  # Changed to BigIntegerField for high mileage
    drive_wheel = models.CharField(max_length=100,blank=True,null=True)
    fuel = models.CharField(max_length=100,blank=True,null=True, db_index=True)
    is_leasing = models.BooleanField(default=False, db_index=True)
    extra_features = models.JSONField(blank=True,null=True)
    options = models.JSONField(blank=True,null=True)
    images = models.JSONField(blank=True,null=True)
    is_special = models.BooleanField(default=False, db_index=True)
    is_luxury = models.BooleanField(default=False, db_index=True)
    inspection_image = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available', db_index=True)
    address = models.CharField(max_length=255,blank=True,null=True)
    shipping = models.CharField(max_length=50, null=True, blank=True)
    plate_number = models.CharField(max_length=100,blank=True,null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    points = models.CharField(max_length=50, null=True, blank=True)
    description = models.TextField(blank=True,null=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['-created_at', 'status']),
            models.Index(fields=['category', '-auction_date']),
            models.Index(fields=['manufacturer', 'year']),
            models.Index(fields=['price', 'mileage']),
        ]
    
    def __str__(self):
        return self.title

    



class CarImage(models.Model):
    car = models.ForeignKey(ApiCar, on_delete=models.CASCADE, related_name='car_images')
    image = models.CharField(max_length=255)
    image_url = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.image






class CarRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'قيد المراجعة'),
        ('processing', 'جاري العمل عليه'),
        ('completed', 'تم التنفيذ'),
        ('cancelled', 'ملغي'),
    ]
    
    name = models.CharField(max_length=100, verbose_name="الاسم")
    phone = models.CharField(max_length=20, verbose_name="رقم الجوال")
    city = models.CharField(max_length=100, verbose_name="المدينة")
    brand = models.CharField(max_length=100, verbose_name="الشركة")
    model = models.CharField(max_length=100, verbose_name="النوع")
    year = models.CharField(max_length=4, verbose_name="الموديل")
    colors = models.CharField(max_length=100, verbose_name="الالوان المفضلة")
    fuel = models.CharField(max_length=50, verbose_name="الوقود")
    details = models.TextField(blank=True, null=True, verbose_name="تفاصيل الطلب")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="حالة الطلب")
    admin_notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات الإدارة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")
    is_read = models.BooleanField(default=False, verbose_name="تمت القراءة")
 
    
class Port(models.Model):
    name = models.CharField(max_length=100)
    
    def __str__(self):
        return self.name
        
    class Meta:
        verbose_name = "ميناء"
        verbose_name_plural = "الموانئ"






class Contact(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class Post(models.Model):
    title = models.CharField(max_length=200, verbose_name="العنوان", db_index=True)
    title_ar = models.CharField(max_length=200, null=True, blank=True, verbose_name="العنوان بالعربي")
    content = models.TextField(verbose_name="المحتوى")
    content_ar = models.TextField(null=True, blank=True, verbose_name="المحتوى بالعربي")
    video_url = models.URLField(null=True, blank=True, verbose_name="رابط الفيديو", help_text="رابط فيديو من YouTube أو Vimeo أو غيرها")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="الكاتب", db_index=True)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, null=True, blank=True, verbose_name="الموقع", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء", db_index=True)
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")
    is_published = models.BooleanField(default=True, verbose_name="منشور", db_index=True)
    views_count = models.IntegerField(default=0, verbose_name="عدد المشاهدات")
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "منشور"
        verbose_name_plural = "المنشورات"
        indexes = [
            models.Index(fields=['tenant', '-created_at']),
            models.Index(fields=['is_published', '-created_at']),
        ]
    
    def __str__(self):
        return self.title_ar if self.title_ar else self.title
    
    def get_video_embed_url(self):
        """Convert video URL to embeddable format"""
        if not self.video_url:
            return None
        
        url = self.video_url
        
        # YouTube
        if 'youtube.com/watch?v=' in url:
            video_id = url.split('watch?v=')[1].split('&')[0]
            return f'https://www.youtube.com/embed/{video_id}?rel=0&modestbranding=1'
        elif 'youtu.be/' in url:
            video_id = url.split('youtu.be/')[1].split('?')[0]
            return f'https://www.youtube.com/embed/{video_id}?rel=0&modestbranding=1'
        
        # Vimeo
        elif 'vimeo.com/' in url:
            video_id = url.split('vimeo.com/')[1].split('?')[0]
            return f'https://player.vimeo.com/video/{video_id}'
        
        # Already an embed URL
        elif 'youtube.com/embed/' in url or 'player.vimeo.com' in url:
            return url
        
        return None
    
    @property
    def likes_count(self):
        return self.postlike_set.count()
    
    @property
    def comments_count(self):
        return self.postcomment_set.filter(is_approved=True).count()


class PostImage(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='images', verbose_name="المنشور")
    image = models.ImageField(upload_to='post_images/', verbose_name="الصورة")
    caption = models.CharField(max_length=200, null=True, blank=True, verbose_name="التعليق")
    order = models.IntegerField(default=0, verbose_name="الترتيب")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['order', 'created_at']
        verbose_name = "صورة المنشور"
        verbose_name_plural = "صور المنشورات"
    
    def __str__(self):
        return f"{self.post.title} - Image {self.order}"


class PostLike(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, verbose_name="المنشور")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="المستخدم")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['post', 'user']
        verbose_name = "إعجاب المنشور"
        verbose_name_plural = "إعجابات المنشورات"
    
    def __str__(self):
        return f"{self.user.username} likes {self.post.title}"


class PostComment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, verbose_name="المنشور")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="المستخدم")
    comment = models.TextField(verbose_name="التعليق")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    is_approved = models.BooleanField(default=True, verbose_name="موافق عليه")
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "تعليق المنشور"
        verbose_name_plural = "تعليقات المنشورات"
    
    def __str__(self):
        return f"{self.user.username} on {self.post.title}"

