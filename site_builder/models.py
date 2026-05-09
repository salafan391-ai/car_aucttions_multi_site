from django.db import models
from django.utils.text import slugify


class Page(models.Model):
    KIND_HOME = "home"
    KIND_ABOUT = "about"
    KIND_CONTACT = "contact"
    KIND_CUSTOM = "custom"
    KIND_CHOICES = [
        (KIND_HOME, "Home"),
        (KIND_ABOUT, "About"),
        (KIND_CONTACT, "Contact"),
        (KIND_CUSTOM, "Custom"),
    ]

    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_CUSTOM)
    slug = models.SlugField(max_length=80, unique=True)
    title = models.CharField(max_length=160)
    title_en = models.CharField(max_length=160, blank=True)
    meta_description = models.CharField(max_length=300, blank=True)
    is_published = models.BooleanField(default=True)
    show_in_nav = models.BooleanField(default=False)
    nav_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nav_order", "title"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind"],
                condition=models.Q(kind__in=["home", "about", "contact"]),
                name="unique_singleton_page_kind",
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_kind_display()})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title_en or self.title) or self.kind
        super().save(*args, **kwargs)


class PageSection(models.Model):
    TYPE_HERO = "hero"
    TYPE_TEXT = "text"
    TYPE_HTML = "html"
    TYPE_FEATURED_CARS = "featured_cars"
    TYPE_BRAND_STRIP = "brand_strip"
    TYPE_GALLERY = "gallery"
    TYPE_CTA = "cta"
    TYPE_CONTACT_FORM = "contact_form"
    TYPE_CHOICES = [
        (TYPE_HERO, "Hero"),
        (TYPE_TEXT, "Text"),
        (TYPE_HTML, "Raw HTML"),
        (TYPE_FEATURED_CARS, "Featured cars"),
        (TYPE_BRAND_STRIP, "Brand strip"),
        (TYPE_GALLERY, "Gallery"),
        (TYPE_CTA, "Call to action"),
        (TYPE_CONTACT_FORM, "Contact form"),
    ]

    page = models.ForeignKey(Page, related_name="sections", on_delete=models.CASCADE)
    type = models.CharField(max_length=32, choices=TYPE_CHOICES)
    order = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(default=True)

    title = models.CharField(max_length=200, blank=True)
    title_en = models.CharField(max_length=200, blank=True)
    subtitle = models.CharField(max_length=300, blank=True)
    subtitle_en = models.CharField(max_length=300, blank=True)
    body = models.TextField(blank=True, help_text="Plain text or HTML, depending on section type.")
    image = models.ImageField(upload_to="site_builder/sections/", blank=True, null=True)

    config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Type-specific options. Examples: "
            "{'cta_label': 'Browse cars', 'cta_url': '/site_cars/'}, "
            "{'limit': 8, 'manufacturer': 'bmw'}, "
            "{'columns': 4}."
        ),
    )

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.page.slug} · {self.get_type_display()} #{self.order}"


class NavLink(models.Model):
    label = models.CharField(max_length=80)
    label_en = models.CharField(max_length=80, blank=True)
    url = models.CharField(
        max_length=300,
        blank=True,
        help_text="Use this OR `page` — `url` wins if both are set.",
    )
    page = models.ForeignKey(
        Page,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="nav_links",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="children",
    )
    order = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(default=True)
    open_in_new_tab = models.BooleanField(default=False)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.label

    @property
    def resolved_url(self):
        if self.url:
            return self.url
        if self.page_id:
            return f"/p/{self.page.slug}/"
        return "#"


class FooterColumn(models.Model):
    title = models.CharField(max_length=80)
    title_en = models.CharField(max_length=80, blank=True)
    order = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title


class FooterLink(models.Model):
    column = models.ForeignKey(FooterColumn, related_name="links", on_delete=models.CASCADE)
    label = models.CharField(max_length=80)
    label_en = models.CharField(max_length=80, blank=True)
    url = models.CharField(max_length=300, blank=True)
    page = models.ForeignKey(
        Page,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="footer_links",
    )
    order = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(default=True)
    open_in_new_tab = models.BooleanField(default=False)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.label

    @property
    def resolved_url(self):
        if self.url:
            return self.url
        if self.page_id:
            return f"/p/{self.page.slug}/"
        return "#"


class ListingConfig(models.Model):
    """Single-row config controlling the public car-listing page filters."""

    SORT_NEWEST = "-created_at"
    SORT_OLDEST = "created_at"
    SORT_PRICE_ASC = "price"
    SORT_PRICE_DESC = "-price"
    SORT_YEAR_DESC = "-year"
    SORT_CHOICES = [
        (SORT_NEWEST, "Newest first"),
        (SORT_OLDEST, "Oldest first"),
        (SORT_PRICE_ASC, "Price: low to high"),
        (SORT_PRICE_DESC, "Price: high to low"),
        (SORT_YEAR_DESC, "Year: newest"),
    ]

    show_search = models.BooleanField(default=True)
    show_manufacturer = models.BooleanField(default=True)
    show_model = models.BooleanField(default=True)
    show_year_range = models.BooleanField(default=True)
    show_price_range = models.BooleanField(default=True)
    show_fuel = models.BooleanField(default=True)
    show_transmission = models.BooleanField(default=True)
    show_body_type = models.BooleanField(default=True)
    show_color = models.BooleanField(default=False)
    show_mileage_range = models.BooleanField(default=False)

    default_sort = models.CharField(max_length=32, choices=SORT_CHOICES, default=SORT_NEWEST)
    page_size = models.PositiveIntegerField(default=24)

    class Meta:
        verbose_name = "Listing configuration"
        verbose_name_plural = "Listing configuration"

    def __str__(self):
        return "Listing configuration"

    def save(self, *args, **kwargs):
        # Enforce singleton — only one row per tenant schema.
        if not self.pk and ListingConfig.objects.exists():
            existing = ListingConfig.objects.first()
            self.pk = existing.pk
        super().save(*args, **kwargs)
