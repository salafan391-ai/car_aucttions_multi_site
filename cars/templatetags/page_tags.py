"""Helpers for turning a chosen page URL into a friendly, bilingual CTA label."""
from django import template
from django.urls import reverse, NoReverseMatch

register = template.Library()

# Friendly, action-oriented labels per known page (ar/en/es/ru) for the
# language switcher. Built lazily against reverse() so paths stay correct.
_PAGE_LABELS = [
    ("home", "", {"ar": "الرئيسية", "en": "Home", "es": "Inicio", "ru": "Главная"}),
    ("car_list", "", {"ar": "تصفح السيارات", "en": "Browse Cars", "es": "Ver coches", "ru": "Смотреть авто"}),
    ("car_list", "?car_type=auction", {"ar": "شاهد المزادات", "en": "View Auctions", "es": "Ver subastas", "ru": "Смотреть аукционы"}),
    ("parts_list", "", {"ar": "تصفح قطع الغيار", "en": "Browse Parts", "es": "Ver repuestos", "ru": "Смотреть запчасти"}),
    ("accessories_list", "", {"ar": "تصفح الإكسسوارات", "en": "Browse Accessories", "es": "Ver accesorios", "ru": "Аксессуары"}),
    ("wishlist", "", {"ar": "المفضلة", "en": "Wishlist", "es": "Favoritos", "ru": "Избранное"}),
    ("contact", "", {"ar": "تواصل معنا", "en": "Contact Us", "es": "Contacto", "ru": "Связаться"}),
]
_GENERIC = {"ar": "اكتشف المزيد", "en": "Learn More", "es": "Saber más", "ru": "Подробнее"}

_MAP = None


def _label_map():
    global _MAP
    if _MAP is None:
        _MAP = {}
        for name, suffix, labels in _PAGE_LABELS:
            try:
                _MAP[reverse(name) + suffix] = labels
            except NoReverseMatch:
                continue
    return _MAP


@register.filter
def page_cta_label(url):
    """Bilingual CTA label dict for a chosen page URL (generic for custom URLs)."""
    if not url:
        return None
    return _label_map().get(str(url).strip(), _GENERIC)
