from django.db import models
from django.contrib.auth.models import User
from cars.models import ApiCar


class SiteCar(models.Model):
    STATUS_CHOICES = [
        ('available', 'متاح'),
        ('sold', 'تم البيع'),
        ('pending', 'قيد الانتظار'),
    ]

    title = models.CharField(max_length=200, verbose_name="العنوان")
    description = models.TextField(blank=True, null=True, verbose_name="الوصف")
    image = models.ImageField(upload_to='site_cars/', blank=True, null=True, verbose_name="صورة رئيسية")
    manufacturer = models.CharField(max_length=100, verbose_name="الشركة المصنعة")
    model = models.CharField(max_length=100, verbose_name="الموديل")
    year = models.IntegerField(verbose_name="سنة الصنع")
    color = models.CharField(max_length=100, blank=True, null=True, verbose_name="اللون")
    mileage = models.BigIntegerField(default=0, verbose_name="المسافة المقطوعة")
    price = models.BigIntegerField(verbose_name="السعر")
    transmission = models.CharField(max_length=100, blank=True, null=True, verbose_name="ناقل الحركة")
    fuel = models.CharField(max_length=100, blank=True, null=True, verbose_name="الوقود")
    body_type = models.CharField(max_length=100, blank=True, null=True, verbose_name="نوع الهيكل")
    engine = models.CharField(max_length=100, blank=True, null=True, verbose_name="المحرك")
    drive_wheel = models.CharField(max_length=100, blank=True, null=True, verbose_name="نظام الدفع")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available', verbose_name="الحالة")
    is_featured = models.BooleanField(default=False, verbose_name="مميزة")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "سيارة الموقع"
        verbose_name_plural = "سيارات الموقع"

    def __str__(self):
        return f"{self.manufacturer} {self.model} {self.year}"


class SiteCarImage(models.Model):
    car = models.ForeignKey(SiteCar, on_delete=models.CASCADE, related_name='gallery', verbose_name="السيارة")
    image = models.ImageField(upload_to='site_cars/', verbose_name="الصورة")
    caption = models.CharField(max_length=200, blank=True, verbose_name="وصف")
    order = models.PositiveIntegerField(default=0, verbose_name="الترتيب")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'created_at']
        verbose_name = "صورة"
        verbose_name_plural = "صور السيارة"

    def __str__(self):
        return f"صورة - {self.car}"


class SiteOrder(models.Model):
    STATUS_CHOICES = [
        ('pending', 'قيد المراجعة'),
        ('accepted', 'مقبول'),
        ('rejected', 'مرفوض'),
        ('completed', 'مكتمل'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='site_orders')
    car = models.ForeignKey(ApiCar, on_delete=models.CASCADE, verbose_name="السيارة")
    offer_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="السعر المعروض")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="الحالة")
    notes = models.TextField(blank=True, verbose_name="ملاحظات العميل")
    admin_notes = models.TextField(blank=True, verbose_name="ملاحظات الإدارة")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "طلب"
        verbose_name_plural = "الطلبات"

    def __str__(self):
        return f"طلب #{self.pk} - {self.car}"


class SiteBill(models.Model):
    order = models.ForeignKey(SiteOrder, on_delete=models.CASCADE, related_name='bills', verbose_name="الطلب")
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="المبلغ")
    receipt_number = models.CharField(max_length=100, blank=True, null=True, verbose_name="رقم الإيصال")
    description = models.CharField(max_length=255, blank=True, verbose_name="الوصف")
    date = models.DateField(verbose_name="التاريخ")
    is_paid = models.BooleanField(default=False, verbose_name="مدفوعة")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']
        verbose_name = "فاتورة"
        verbose_name_plural = "الفواتير"

    def __str__(self):
        return f"فاتورة {self.receipt_number or self.pk} - {self.order}"


class SiteRating(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='site_ratings')
    car = models.ForeignKey(ApiCar, on_delete=models.CASCADE, verbose_name="السيارة")
    rating = models.IntegerField(verbose_name="التقييم")
    comment = models.TextField(blank=True, verbose_name="التعليق")
    is_approved = models.BooleanField(default=False, verbose_name="موافق عليه")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "تقييم"
        verbose_name_plural = "التقييمات"
        unique_together = ['user', 'car']

    def __str__(self):
        return f"{self.user} - {self.car} ({self.rating}/5)"


class SiteQuestion(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='site_questions')
    car = models.ForeignKey(ApiCar, on_delete=models.CASCADE, null=True, blank=True, verbose_name="السيارة")
    question = models.TextField(verbose_name="السؤال")
    answer = models.TextField(blank=True, null=True, verbose_name="الإجابة")
    is_answered = models.BooleanField(default=False, verbose_name="تمت الإجابة")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "سؤال"
        verbose_name_plural = "الأسئلة"

    def __str__(self):
        return f"{self.user} - {self.question[:50]}"


class SiteSoldCar(models.Model):
    car = models.ForeignKey(ApiCar, on_delete=models.CASCADE, verbose_name="السيارة")
    buyer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='purchased_cars', verbose_name="المشتري")
    sale_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="سعر البيع")
    original_price = models.BigIntegerField(null=True, blank=True, verbose_name="السعر الأصلي")
    sold_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ البيع")
    notes = models.TextField(blank=True, verbose_name="ملاحظات")

    class Meta:
        ordering = ['-sold_at']
        verbose_name = "سيارة مباعة"
        verbose_name_plural = "السيارات المباعة"

    def __str__(self):
        return f"{self.car} - {self.sale_price}"


class SiteMessage(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages', verbose_name="المرسل")
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages', verbose_name="المستلم")
    subject = models.CharField(max_length=255, verbose_name="الموضوع")
    body = models.TextField(verbose_name="الرسالة")
    is_read = models.BooleanField(default=False, verbose_name="مقروءة")
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies', verbose_name="رد على")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "رسالة"
        verbose_name_plural = "الرسائل"

    def __str__(self):
        return f"{self.sender} → {self.recipient}: {self.subject}"


class SiteEmailLog(models.Model):
    STATUS_CHOICES = [
        ('sent', 'تم الإرسال'),
        ('failed', 'فشل'),
        ('pending', 'قيد الإرسال'),
    ]
    TYPE_CHOICES = [
        ('order_placed', 'طلب جديد'),
        ('order_status', 'تحديث حالة الطلب'),
        ('welcome', 'ترحيب'),
        ('custom', 'رسالة مخصصة'),
        ('broadcast', 'رسالة جماعية'),
    ]

    recipient_email = models.EmailField(verbose_name="البريد الإلكتروني")
    recipient_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المستخدم")
    subject = models.CharField(max_length=255, verbose_name="الموضوع")
    body = models.TextField(verbose_name="المحتوى")
    email_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='custom', verbose_name="النوع")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending', verbose_name="الحالة")
    error_message = models.TextField(blank=True, verbose_name="رسالة الخطأ")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "سجل بريد"
        verbose_name_plural = "سجلات البريد"

    def __str__(self):
        return f"{self.email_type} → {self.recipient_email} ({self.status})"
