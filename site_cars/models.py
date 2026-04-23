from django.db import models
from django.contrib.auth.models import User
from cars.models import ApiCar
from cars.normalization import (
    normalize_name, normalize_fuel, normalize_transmission,
)
from site_cars.image_utils import optimize_image


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
    inspection_image = models.ImageField(upload_to='site_cars/inspections/', blank=True, null=True, verbose_name="صورة الفحص")
    # Extra specs surfaced on the source listing (HappyCar) that weren't
    # captured by the earlier importer. Freeform; safe for admin-created rows.
    trim = models.CharField(max_length=100, blank=True, default='', verbose_name="الطراز")
    engine_cc = models.IntegerField(null=True, blank=True, verbose_name="حجم المحرك (سي سي)")
    month = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="شهر الصنع")
    location = models.CharField(max_length=200, blank=True, default='', verbose_name="موقع التخزين")
    registration_no = models.CharField(
        max_length=50, blank=True, default='', db_index=True,
        verbose_name="رقم التسجيل",
    )
    source_url = models.URLField(
        max_length=500, blank=True, default='',
        verbose_name="رابط الإعلان المصدر",
    )
    auction_end = models.DateTimeField(null=True, blank=True, verbose_name="نهاية المزاد")
    source_status = models.CharField(
        max_length=20, blank=True, default='', db_index=True,
        verbose_name="حالة المصدر",
        help_text="رمز الحالة الأصلي من المصدر (مثال: 폐차 / 구제 / 부품).",
    )
    claims_count = models.PositiveSmallIntegerField(
        default=0, db_index=True,
        verbose_name="عدد الحوادث",
        help_text="إجمالي مطالبات التأمين (الذاتية + الطرف الآخر).",
    )
    insurance_history = models.JSONField(
        null=True, blank=True,
        verbose_name="سجل التأمين",
        help_text="البيانات الخام: plate_changes / owner_changes / own_damage / opposing_damage.",
    )
    # External-source identifiers (e.g. HappyCar imports). Null for admin-created rows.
    external_id = models.CharField(
        max_length=50, null=True, blank=True, unique=True, db_index=True,
        verbose_name="المعرف الخارجي",
        help_text="مفتاح استيراد خارجي — مثال: hc_896409",
    )
    external_image_url = models.URLField(
        max_length=500, null=True, blank=True,
        verbose_name="رابط الصورة الخارجي",
        help_text="يستخدم بدل رفع الصورة عند استيراد السيارة من مصدر خارجي",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "سيارة الموقع"
        verbose_name_plural = "سيارات الموقع"

    def __str__(self):
        return f"{self.manufacturer} {self.model} {self.year}"

    def save(self, *args, **kwargs):
        # Normalize enum-ish fields to lowercase so they line up with the
        # translation dicts in cars.utils (fuel_types_dict, car_models_dict,
        # transmission_types_dict, etc.) and the |pretty_en / |translate_*
        # filters used in templates.
        self.manufacturer = normalize_name(self.manufacturer) or ''
        self.model = normalize_name(self.model) or ''
        self.fuel = normalize_fuel(self.fuel) if self.fuel else self.fuel
        self.transmission = normalize_transmission(self.transmission) if self.transmission else self.transmission
        self.body_type = normalize_name(self.body_type) if self.body_type else self.body_type
        self.color = normalize_name(self.color) if self.color else self.color
        if self.image and getattr(self.image, '_file', None) is not None:
            self.image = optimize_image(self.image, max_width=1200, max_height=900, quality=85)
        if self.inspection_image and getattr(self.inspection_image, '_file', None) is not None:
            self.inspection_image = optimize_image(self.inspection_image, max_width=1200, max_height=900, quality=85)
        super().save(*args, **kwargs)


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

    def save(self, *args, **kwargs):
        if self.image and getattr(self.image, '_file', None) is not None:
            self.image = optimize_image(self.image, max_width=1200, max_height=900, quality=85)
        super().save(*args, **kwargs)


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
    order = models.ForeignKey(SiteOrder, on_delete=models.CASCADE, related_name='bills', null=True, blank=True, verbose_name="الطلب")
    site_car = models.ForeignKey(SiteCar, on_delete=models.SET_NULL, related_name='bills', null=True, blank=True, verbose_name="السيارة")
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="المبلغ")
    receipt_number = models.CharField(max_length=100, blank=True, null=True, db_index=True, verbose_name="رقم الإيصال")
    description = models.CharField(max_length=255, blank=True, verbose_name="الوصف")
    buyer_name = models.CharField(max_length=200, blank=True, default='', verbose_name="اسم المشتري")
    buyer_id_number = models.CharField(max_length=50, blank=True, default='', verbose_name="رقم الهوية")
    buyer_phone = models.CharField(max_length=50, blank=True, default='', verbose_name="جوال المشتري")
    buyer_address = models.CharField(max_length=255, blank=True, default='', verbose_name="عنوان المشتري")
    date = models.DateField(verbose_name="التاريخ")
    is_paid = models.BooleanField(default=False, verbose_name="مدفوعة")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']
        verbose_name = "فاتورة"
        verbose_name_plural = "الفواتير"

    def __str__(self):
        return f"فاتورة {self.receipt_number or self.pk}"

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            super().save(*args, **kwargs)
            self.receipt_number = f"INV-{self.date.strftime('%Y%m%d')}-{self.pk:05d}"
            type(self).objects.filter(pk=self.pk).update(receipt_number=self.receipt_number)
            return
        super().save(*args, **kwargs)


class SiteShipment(models.Model):
    STATUS_CHOICES = [
        ('preparing', 'قيد التجهيز'),
        ('loaded', 'تم التحميل'),
        ('in_transit', 'قيد الشحن'),
        ('arrived', 'وصلت الميناء'),
        ('delivered', 'تم التسليم'),
        ('cancelled', 'ملغي'),
    ]

    bill = models.OneToOneField(SiteBill, on_delete=models.CASCADE, related_name='shipment', verbose_name="الفاتورة")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='preparing', db_index=True, verbose_name="الحالة")
    shipping_company = models.CharField(max_length=150, blank=True, default='', verbose_name="شركة الشحن")
    vessel_name = models.CharField(max_length=150, blank=True, default='', verbose_name="اسم السفينة")
    container_number = models.CharField(max_length=50, blank=True, default='', db_index=True, verbose_name="رقم الحاوية")
    bill_of_lading = models.CharField(max_length=100, blank=True, default='', db_index=True, verbose_name="بوليصة الشحن")
    origin_port = models.CharField(max_length=150, blank=True, default='', verbose_name="ميناء الشحن")
    destination_port = models.CharField(max_length=150, blank=True, default='', verbose_name="ميناء الوصول")
    destination_country = models.CharField(max_length=100, blank=True, default='', verbose_name="دولة الوصول")
    etd = models.DateField(null=True, blank=True, verbose_name="تاريخ المغادرة المتوقع")
    eta = models.DateField(null=True, blank=True, verbose_name="تاريخ الوصول المتوقع")
    delivered_at = models.DateField(null=True, blank=True, verbose_name="تاريخ التسليم")
    shipping_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="تكلفة الشحن")
    tracking_url = models.URLField(max_length=500, blank=True, default='', verbose_name="رابط التتبع")
    notes = models.TextField(blank=True, default='', verbose_name="ملاحظات")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "شحنة"
        verbose_name_plural = "الشحنات"

    def __str__(self):
        return f"شحنة {self.bill.receipt_number} ({self.get_status_display()})"


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
