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
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    car = models.ForeignKey('ApiCar', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'car']
    
    def __str__(self):
        return f"{self.user.username} - {self.car.title}"

class ApiCar(models.Model):
    STATUS_CHOICES = [
        ('available', 'متاح'),
        ('sold', 'تم البيع'),
        ('pending', 'قيد الانتظار'),
    ]
    car_id = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=100)
    image = models.CharField(max_length=255, null=True, blank=True)
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, blank=True, null=True)
    auction_date = models.DateTimeField(null=True, blank=True)
    auction_name = models.CharField(max_length=100,null=True,blank=True)
    vin = models.CharField(max_length=100,null=True,blank=True)
    lot_number = models.CharField(max_length=100, unique=True, db_index=True)
    model = models.ForeignKey(CarModel, on_delete=models.CASCADE)
    year = models.IntegerField()
    badge = models.ForeignKey(CarBadge, on_delete=models.CASCADE)
    color = models.ForeignKey(CarColor, on_delete=models.CASCADE)
    seat_color = models.ForeignKey(CarSeatColor, on_delete=models.CASCADE,blank=True,null=True)
    seat_count = models.CharField(max_length=100,blank=True,null=True)
    transmission = models.CharField(max_length=100,blank=True,null=True)
    engine = models.CharField(max_length=100,blank=True,null=True)
    conition = models.CharField(max_length=100,blank=True,null=True)
    body = models.ForeignKey(BodyType, on_delete=models.CASCADE,blank=True,null=True)
    power = models.IntegerField(null=True,blank=True)
    price = models.BigIntegerField()  # Changed to BigIntegerField for large prices
    mileage = models.BigIntegerField()  # Changed to BigIntegerField for high mileage
    drive_wheel = models.CharField(max_length=100,blank=True,null=True)
    fuel = models.CharField(max_length=100,blank=True,null=True)
    is_leasing = models.BooleanField(default=False)
    extra_features = models.JSONField(blank=True,null=True)
    options = models.JSONField(blank=True,null=True)
    images = models.JSONField(blank=True,null=True)
    is_special = models.BooleanField(default=False)
    is_luxury = models.BooleanField(default=False)
    inspection_image = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    address = models.CharField(max_length=255,blank=True,null=True)
    shipping = models.CharField(max_length=50, null=True, blank=True)
    plate_number = models.CharField(max_length=100,blank=True,null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    points = models.CharField(max_length=50, null=True, blank=True)
    description = models.TextField(blank=True,null=True)
    
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

