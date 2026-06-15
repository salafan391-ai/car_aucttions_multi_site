from django.db import models
from django.urls import reverse

from site_cars.image_utils import optimize_image


class ShopItem(models.Model):
    """A per-tenant catalogue item — either a car PART or an ACCESSORY.

    One model backs both features; the `kind` field separates them so each
    gets its own public listing/detail pages and its own staff CRUD, while
    sharing the same fields, image handling and admin.
    """

    KIND_CHOICES = [
        ("part", "قطع غيار"),
        ("accessory", "إكسسوارات"),
    ]
    CONDITION_CHOICES = [
        ("new", "جديد"),
        ("used", "مستعمل"),
    ]
    CURRENCY_CHOICES = [
        ("SAR", "ريال سعودي SAR"),
        ("AED", "درهم إماراتي AED"),
        ("USD", "دولار USD"),
        ("EUR", "يورو EUR"),
        ("KRW", "وون كوري KRW"),
    ]

    kind = models.CharField(max_length=12, choices=KIND_CHOICES, default="part", db_index=True, verbose_name="النوع")
    name = models.CharField(max_length=200, verbose_name="الاسم")
    category = models.CharField(max_length=120, blank=True, default="", verbose_name="الفئة")
    brand = models.CharField(max_length=120, blank=True, default="", verbose_name="الماركة")

    price = models.BigIntegerField(null=True, blank=True, verbose_name="السعر", help_text="اتركه فارغاً لعرض «السعر عند الطلب»")
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="SAR", verbose_name="العملة")
    condition = models.CharField(max_length=10, choices=CONDITION_CHOICES, default="new", verbose_name="الحالة")

    in_stock = models.BooleanField(default=True, verbose_name="متوفر")
    is_featured = models.BooleanField(default=False, verbose_name="مميّز")

    description = models.TextField(blank=True, default="", verbose_name="الوصف")
    image = models.ImageField(upload_to="site_shop/", blank=True, null=True, verbose_name="الصورة الرئيسية")

    # Compatibility — which cars this part/accessory fits
    fits_make = models.CharField(max_length=120, blank=True, default="", verbose_name="يناسب الماركة")
    fits_model = models.CharField(max_length=120, blank=True, default="", verbose_name="يناسب الموديل")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_featured", "-created_at"]
        verbose_name = "قطعة / إكسسوار"
        verbose_name_plural = "قطع الغيار والإكسسوارات"
        indexes = [models.Index(fields=["kind", "-created_at"])]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.name}"

    def get_absolute_url(self):
        name = "accessories_detail" if self.kind == "accessory" else "parts_detail"
        return reverse(name, args=[self.pk])

    def save(self, *args, **kwargs):
        if self.image and hasattr(self.image, "file"):
            try:
                self.image = optimize_image(self.image, max_width=1200, max_height=900, quality=85)
            except Exception:
                pass
        super().save(*args, **kwargs)


class ShopItemImage(models.Model):
    """Extra gallery images for a ShopItem."""

    item = models.ForeignKey(ShopItem, related_name="images", on_delete=models.CASCADE)
    image = models.ImageField(upload_to="site_shop/", verbose_name="صورة")
    caption = models.CharField(max_length=200, blank=True, default="")
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "created_at"]

    def __str__(self):
        return f"Image #{self.pk} for {self.item_id}"

    def save(self, *args, **kwargs):
        if self.image and hasattr(self.image, "file"):
            try:
                self.image = optimize_image(self.image, max_width=1200, max_height=900, quality=85)
            except Exception:
                pass
        super().save(*args, **kwargs)
