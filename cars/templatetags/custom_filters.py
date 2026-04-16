from django import template
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
from cars.utils import OPTION_TRANSLATIONS, address_ar, car_models_dict, fuel_types_dict, transmission_types_dict, colors_dict

register = template.Library()


def _force_https(url):
    """Upgrade http:// to https:// to prevent mixed-content browser blocks."""
    if url and url.startswith('http://'):
        return 'https://' + url[7:]
    return url


def _resize_encar_url(url, width, height):
    """
    Rewrite encar.com CDN impolicy params to the requested dimensions.
    Always returns https:// to avoid mixed-content browser blocks.
    Falls back to the (https-upgraded) original URL for non-encar images.
    """
    url = _force_https(url)
    if not url or 'encar.com' not in url:
        return url
    parsed = urlparse(url)
    # Replace impolicy dimensions — keep other params intact
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs['impolicy'] = ['heightRate']
    qs['rh'] = [str(height)]
    qs['cw'] = [str(width)]
    qs['ch'] = [str(height)]
    qs['cg'] = ['Center']
    new_query = urlencode({k: v[0] for k, v in qs.items()})
    return urlunparse(parsed._replace(query=new_query))


@register.filter
def img_thumb(url):
    """Resize to card thumbnail — 600×450 (4:3, 2× for retina mobile)."""
    return _resize_encar_url(url, 600, 450)


@register.filter
def img_small(url):
    """Resize to small card — 400×300 (home page cards)."""
    return _resize_encar_url(url, 400, 300)


@register.filter
def img_full(url):
    """Full-res for detail/lightbox — 1200×900."""
    return _resize_encar_url(url, 1200, 900)


@register.filter
def https_url(url):
    """Upgrade any http:// image URL to https:// to prevent mixed-content blocks."""
    return _force_https(url)




@register.filter
def translate_option(value):
    """
    Translates a given option value using the OPTION_TRANSLATIONS mapping.
    If the value is not found in the mapping, it returns the original value.
    """
    return OPTION_TRANSLATIONS.get('ar', {}).get(value, value)



@register.filter
def ar_address(value):
    if not value:
        return value
    split_value = value.split()[0]
    return address_ar.get(split_value, value)





@register.filter(name='translate_model')
def translate_model(value):
    """
    Accepts either a CarModel instance or a plain string model name.
    Returns the Arabic translation from car_models_dict, or the English
    name if no translation exists.
    """
    # If value is a model object, extract the name string first.
    name = getattr(value, 'name', value)
    # Prefer an explicit name_ar attribute set dynamically in views.
    name_ar = getattr(value, 'name_ar', None)
    if name_ar:
        return name_ar
    return car_models_dict.get(name.lower(), name.lower())


@register.filter(name='translate_manufacturer')
def translate_manufacturer(value):
    """
    Accepts either a Manufacturer instance or a plain string name.
    Returns name_ar if set, otherwise the lowercased English name.
    """
    name = getattr(value, 'name', value)
    name_ar = getattr(value, 'name_ar', None)
    if name_ar:
        return name_ar
    return name.lower() if isinstance(name, str) else name


@register.filter(name='translate_fuel')
def translate_fuel(value):
    value = value.lower() if isinstance(value, str) else value
    return fuel_types_dict.get(value, value)



@register.filter(name='translate_transmission')
def translate_transmission(value):
    value = value.lower() if isinstance(value, str) else value
    return transmission_types_dict.get(value, value)



@register.filter(name='translate_color')
def translate_color(value):
    value = value.lower() if isinstance(value, str) else value
    return colors_dict.get(value, value)