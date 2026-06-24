import re

from django.db import models
from django.urls import reverse

from site_cars.image_utils import optimize_image


def categories_for(kind):
    """Distinct categories actually in use for this kind (dynamic, from the
    tenant's own items — populated by imports/staff, not hardcoded). Deduped
    case-insensitively so whitespace/casing variants collapse to one."""
    seen = {}
    for c in (ShopItem.objects.filter(kind=kind)
              .exclude(category="").values_list("category", flat=True)):
        c = re.sub(r"\s+", " ", c or "").strip()
        if c and c.lower() not in seen:
            seen[c.lower()] = c
    return sorted(seen.values(), key=lambda s: s.lower())


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
    ORIGIN_CHOICES = [
        ("genuine", "أصلي / وكالة"),
        ("aftermarket", "تجاري / بديل"),
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

    origin = models.CharField(max_length=12, choices=ORIGIN_CHOICES, blank=True, default="", verbose_name="المصدر", help_text="أصلي (وكالة) أو تجاري (بديل)")
    part_number = models.CharField(max_length=80, blank=True, default="", verbose_name="رقم القطعة", help_text="رقم القطعة من المصنّع (MPN) أو رقم الوكالة OEM")
    part_number_norm = models.CharField(max_length=80, blank=True, default="", db_index=True, editable=False)

    in_stock = models.BooleanField(default=True, verbose_name="متوفر")
    is_featured = models.BooleanField(default=False, verbose_name="مميّز")

    description = models.TextField(blank=True, default="", verbose_name="الوصف")
    image = models.ImageField(upload_to="site_shop/", blank=True, null=True, verbose_name="الصورة الرئيسية")

    # Compatibility — which cars this part/accessory fits
    fits_make = models.CharField(max_length=120, blank=True, default="", verbose_name="يناسب الماركة")
    fits_model = models.CharField(max_length=120, blank=True, default="", verbose_name="يناسب الموديل")

    # Import bookkeeping — lets an importer upsert instead of duplicating.
    source = models.CharField(max_length=40, blank=True, default="", db_index=True, verbose_name="المصدر (استيراد)")
    external_id = models.CharField(max_length=120, blank=True, default="", db_index=True, verbose_name="المعرّف الخارجي")

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
        # Tidy whitespace so filter values / category lists stay consistent.
        self.category = re.sub(r"\s+", " ", self.category or "").strip()
        self.brand = re.sub(r"\s+", " ", self.brand or "").strip()
        # Loose part-number matching: keep only alphanumerics, uppercased, so
        # "GR3Z-10346-Q" / "GR3Z 10346 Q" / "gr3z10346q" all match.
        self.part_number_norm = re.sub(r"[^A-Za-z0-9]", "", self.part_number or "").upper()
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


class ShopRequest(models.Model):
    """A customer request for a part/accessory that's not in the catalogue —
    submitted from the empty-catalogue form on the public parts/accessories page."""
    KIND_CHOICES = [
        ("part", "قطع غيار"),
        ("accessory", "إكسسوارات"),
    ]
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="part", verbose_name="النوع")
    car_vin = models.CharField(max_length=40, blank=True, default="", verbose_name="رقم الهيكل (VIN)")
    car_description = models.TextField(blank=True, default="", verbose_name="وصف السيارة")
    phone = models.CharField(max_length=30, verbose_name="رقم الهاتف")
    email = models.EmailField(blank=True, default="", verbose_name="البريد الإلكتروني")
    item_description = models.TextField(verbose_name="وصف القطعة/الإكسسوار المطلوب")
    is_handled = models.BooleanField(default=False, verbose_name="تمت المعالجة")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "طلب قطعة/إكسسوار"
        verbose_name_plural = "طلبات القطع والإكسسوارات"

    def __str__(self):
        return f"{self.get_kind_display()} request — {self.phone}"
