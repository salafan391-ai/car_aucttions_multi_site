from django import forms

from .models import Page, PageSection


# Friendly section types for the editor: key -> (label_ar, emoji, which fields it uses)
SECTION_META = {
    "hero":          {"label": "بانر رئيسي (Hero)", "icon": "🖼️", "uses": ["title", "subtitle", "body", "image", "cta"]},
    "text":          {"label": "نص / فقرة", "icon": "📝", "uses": ["title", "subtitle", "body"]},
    "cta":           {"label": "دعوة لإجراء (CTA)", "icon": "🎯", "uses": ["title", "subtitle", "image", "cta"]},
    "featured_cars": {"label": "سيارات مختارة", "icon": "🚗", "uses": ["title", "subtitle", "cars"]},
    "gallery":       {"label": "معرض صور", "icon": "🖼️", "uses": ["title", "subtitle", "image"]},
    "brand_strip":   {"label": "شريط الماركات", "icon": "🏷️", "uses": ["title"]},
    "contact_form":  {"label": "نموذج تواصل", "icon": "✉️", "uses": ["title", "subtitle"]},
    "html":          {"label": "HTML مخصّص", "icon": "</>", "uses": ["title", "body"]},
}

BG_CHOICES = [("default", "افتراضي"), ("muted", "خلفية فاتحة"), ("brand", "لون العلامة"), ("dark", "داكن")]
ALIGN_CHOICES = [("start", "محاذاة للبداية"), ("center", "توسيط")]
WIDTH_CHOICES = [("normal", "عرض عادي"), ("wide", "عريض"), ("full", "عرض كامل")]

_TEXT = "w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"


class PageForm(forms.ModelForm):
    class Meta:
        model = Page
        fields = ["title", "title_en", "slug", "meta_description", "is_published", "show_in_nav", "nav_order"]
        widgets = {
            "title": forms.TextInput(attrs={"class": _TEXT, "placeholder": "من نحن"}),
            "title_en": forms.TextInput(attrs={"class": _TEXT, "placeholder": "About Us"}),
            "slug": forms.TextInput(attrs={"class": _TEXT, "placeholder": "about", "dir": "ltr"}),
            "meta_description": forms.TextInput(attrs={"class": _TEXT}),
            "nav_order": forms.NumberInput(attrs={"class": _TEXT}),
        }

    def clean_slug(self):
        from django.utils.text import slugify
        slug = (self.cleaned_data.get("slug") or "").strip()
        return slug or slugify(self.cleaned_data.get("title_en") or self.cleaned_data.get("title") or "page")


class SectionForm(forms.ModelForm):
    # config-backed extras (presets + per-type options)
    cta_label = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": _TEXT, "placeholder": "تصفح السيارات"}))
    cta_url = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": _TEXT, "dir": "ltr", "placeholder": "/cars/"}))
    bg = forms.ChoiceField(choices=BG_CHOICES, required=False, widget=forms.Select(attrs={"class": _TEXT}))
    align = forms.ChoiceField(choices=ALIGN_CHOICES, required=False, widget=forms.Select(attrs={"class": _TEXT}))
    width = forms.ChoiceField(choices=WIDTH_CHOICES, required=False, widget=forms.Select(attrs={"class": _TEXT}))
    limit = forms.IntegerField(required=False, min_value=1, max_value=24, widget=forms.NumberInput(attrs={"class": _TEXT}))
    columns = forms.IntegerField(required=False, min_value=1, max_value=6, widget=forms.NumberInput(attrs={"class": _TEXT}))
    manufacturer = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": _TEXT, "dir": "ltr"}))

    _CONFIG_TEXT = ["cta_label", "cta_url", "bg", "align", "width", "manufacturer"]
    _CONFIG_NUM = ["limit", "columns"]

    class Meta:
        model = PageSection
        fields = ["type", "title", "title_en", "subtitle", "subtitle_en", "body", "image", "is_visible"]
        widgets = {
            "type": forms.Select(attrs={"class": _TEXT}),
            "title": forms.TextInput(attrs={"class": _TEXT}),
            "title_en": forms.TextInput(attrs={"class": _TEXT}),
            "subtitle": forms.TextInput(attrs={"class": _TEXT}),
            "subtitle_en": forms.TextInput(attrs={"class": _TEXT}),
            "body": forms.Textarea(attrs={"class": _TEXT, "rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cfg = (getattr(self.instance, "config", None) or {})
        for k in self._CONFIG_TEXT + self._CONFIG_NUM:
            if cfg.get(k) not in (None, ""):
                self.fields[k].initial = cfg.get(k)
        if not self.fields["bg"].initial:
            self.fields["bg"].initial = "default"
        if not self.fields["align"].initial:
            self.fields["align"].initial = "start"
        if not self.fields["width"].initial:
            self.fields["width"].initial = "normal"

    def save(self, commit=True):
        obj = super().save(commit=False)
        cfg = dict(obj.config or {})
        for k in self._CONFIG_TEXT:
            v = (self.cleaned_data.get(k) or "").strip()
            if v:
                cfg[k] = v
            elif k in cfg:
                del cfg[k]
        for k in self._CONFIG_NUM:
            v = self.cleaned_data.get(k)
            if v:
                cfg[k] = int(v)
            elif k in cfg:
                del cfg[k]
        obj.config = cfg
        if commit:
            obj.save()
        return obj
