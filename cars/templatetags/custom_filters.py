from django import template
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
from cars.utils import OPTION_TRANSLATIONS, address_ar, address_en, body_types_dict, car_models_dict, fuel_types_dict, transmission_types_dict, colors_dict

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


# Words that must stay fully uppercase in English display.
_UPPERCASE_TOKENS = {
    'bmw', 'gmc', 'mg', 'vw', 'suv', 'cvt', 'cng', 'lpg', 'vin', 'rv', 'ev',
    'hud', 'epb', 'abs', 'usa', 'uk', 'uae', 'ksa', 'kia', 'id',
}

# Manual overrides for tokens that aren't just "uppercase".
_TOKEN_OVERRIDES = {
    'mclaren': 'McLaren',
    'rolls-royce': 'Rolls-Royce',
    'mercedes-benz': 'Mercedes-Benz',
    'mercedesbenz': 'Mercedes-Benz',
    'alfa': 'Alfa',
    'romeo': 'Romeo',
    'landrover': 'Land Rover',
    'rangerover': 'Range Rover',
    'astonmartin': 'Aston Martin',
    'iphone': 'iPhone',
}


def _prettify_token(tok):
    low = tok.lower()
    if low in _TOKEN_OVERRIDES:
        return _TOKEN_OVERRIDES[low]
    if low in _UPPERCASE_TOKENS:
        return low.upper()
    # Title-case but preserve hyphens / slashes / parentheses
    return low[:1].upper() + low[1:] if low else low


@register.filter(name='pretty_en')
def pretty_en(value):
    """
    Proper-case an English string that may have been stored lowercase in the DB.
    Preserves acronyms like BMW, SUV, CVT, VIN, etc.

    "hyundai" → "Hyundai"
    "bmw"     → "BMW"
    "sonata"  → "Sonata"
    "pearl two-tone" → "Pearl Two-Tone"
    """
    if not value or not isinstance(value, str):
        return value
    # Split on whitespace first, keep internal punctuation.
    out = []
    for word in value.split(' '):
        # Handle hyphen / slash / plus / parentheses splits inside a word.
        parts = []
        buf = ''
        seps = []
        for ch in word:
            if ch in '-/+()':
                parts.append(buf)
                seps.append(ch)
                buf = ''
            else:
                buf += ch
        parts.append(buf)
        pretty_parts = [_prettify_token(p) if p else p for p in parts]
        # Reassemble
        assembled = pretty_parts[0]
        for i, sep in enumerate(seps):
            assembled += sep + pretty_parts[i + 1]
        out.append(assembled)
    return ' '.join(out)




@register.filter
def translate_option(value):
    """
    Translates a given option value using the OPTION_TRANSLATIONS mapping.
    If the value is not found in the mapping, it returns the original value.
    """
    return OPTION_TRANSLATIONS.get('ar', {}).get(value, value)


@register.filter
def translate_option_en(value):
    return OPTION_TRANSLATIONS.get('en', {}).get(value, value)



@register.filter
def ar_address(value):
    if not value:
        return value
    split_value = value.split()[0]
    return address_ar.get(split_value, value)


@register.filter
def en_address(value):
    if not value:
        return value
    split_value = value.split()[0]
    return address_en.get(split_value, value)





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


@register.filter(name='translate_body')
def translate_body(value):
    """
    Return the Arabic translation of a body type (from DB, lowercase).
    Falls back to the prettified English name if no translation exists.
    """
    name = getattr(value, 'name', value)
    name_ar = getattr(value, 'name_ar', None)
    if name_ar:
        return name_ar
    if not isinstance(name, str):
        return name
    return body_types_dict.get(name.lower(), pretty_en(name))