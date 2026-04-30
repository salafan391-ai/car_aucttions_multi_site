from django import template
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
from cars.utils import OPTION_TRANSLATIONS, address_ar, address_en, body_types_dict, car_models_dict, fuel_types_dict, transmission_types_dict, colors_dict

# Generated dicts for extra languages (es, ru, …). Absent if the
# `translate_enums` command hasn't been run yet — gracefully fall back.
try:
    from cars import utils_i18n as _i18n
except ImportError:
    _i18n = None


def _extra_dict(enum_name: str, lang: str):
    """Look up a lang-specific enum dict (e.g. colors_dict_es) on utils_i18n."""
    if _i18n is None:
        return {}
    return getattr(_i18n, f"{enum_name}_{lang}", {})


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
def translate_option(value, lang='ar'):
    """
    Translates a given option value using the OPTION_TRANSLATIONS mapping
    (or, for non-ar/en, the auto-generated options_dict_<lang>).
    Falls back to the original value if not found.
    """
    if lang in ('ar', 'en'):
        return OPTION_TRANSLATIONS.get(lang, {}).get(value, value)
    return _extra_dict('options_dict', lang).get(value, value)


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


@register.filter
def translate_address(value, lang='ar'):
    """
    Look up a Korean address prefix in the address_<lang> table.
    Falls back to English, then to the raw value. Used for es/ru; ar/en still
    use the dedicated `ar_address` / `en_address` filters for back-compat.
    """
    if not value:
        return value
    split_value = value.split()[0]
    if lang == 'ar':
        return address_ar.get(split_value, value)
    if lang == 'en':
        return address_en.get(split_value, value)
    extra = _extra_dict('address', lang)
    return extra.get(split_value) or address_en.get(split_value, value)





def _translate_enum(value, lang, ar_dict, dict_stem, missing_fallback=None):
    """Shared lookup for enum filters that optionally accept a target lang."""
    if not isinstance(value, str):
        return value
    key = value.lower()
    if lang == 'ar':
        return ar_dict.get(key, key)
    if lang == 'en':
        return pretty_en(value)
    translated = _extra_dict(dict_stem, lang).get(key)
    if translated:
        return translated
    # Fall back to English pretty-cased if the extra dict is missing.
    return missing_fallback(value) if missing_fallback else pretty_en(value)


@register.filter(name='translate_model')
def translate_model(value, lang='ar'):
    """
    Accepts either a CarModel instance or a plain string model name.
    Returns the Arabic translation from car_models_dict by default; for
    other target languages falls back to the generated car_models_dict_<lang>
    or the English name.
    """
    # If value is a model object, extract the name string first.
    obj = value
    name = getattr(obj, 'name', obj)
    # Prefer an explicit name_ar attribute set dynamically in views (for ar only).
    name_ar = getattr(obj, 'name_ar', None)
    if lang == 'ar' and name_ar:
        return name_ar
    if not isinstance(name, str):
        return name
    if lang == 'ar':
        return car_models_dict.get(name.lower(), name.lower())
    if lang == 'en':
        return pretty_en(name)
    return _extra_dict('car_models_dict', lang).get(name.lower()) or pretty_en(name)


@register.filter(name='translate_manufacturer')
def translate_manufacturer(value, lang='ar'):
    """
    Accepts either a Manufacturer instance or a plain string name.
    Returns name_ar for Arabic, pretty_en for everything else (brand names
    generally don't localize).
    """
    obj = value
    name = getattr(obj, 'name', obj)
    name_ar = getattr(obj, 'name_ar', None)
    if lang == 'ar' and name_ar:
        return name_ar
    if not isinstance(name, str):
        return name
    if lang == 'ar':
        return name.lower()
    return pretty_en(name)


@register.filter(name='translate_fuel')
def translate_fuel(value, lang='ar'):
    return _translate_enum(value, lang, fuel_types_dict, 'fuel_types_dict')


@register.filter(name='translate_transmission')
def translate_transmission(value, lang='ar'):
    return _translate_enum(value, lang, transmission_types_dict, 'transmission_types_dict')


@register.filter(name='translate_color')
def translate_color(value, lang='ar'):
    return _translate_enum(value, lang, colors_dict, 'colors_dict')


@register.filter(name='translate_body')
def translate_body(value, lang='ar'):
    """
    Return a body type translated for the given language. Body type values
    are stored as lowercase English (e.g. 'suv', 'sedan') or, for ar, may
    come in via an object with a name_ar attribute.
    """
    obj = value
    name = getattr(obj, 'name', obj)
    name_ar = getattr(obj, 'name_ar', None)
    if lang == 'ar' and name_ar:
        return name_ar
    if not isinstance(name, str):
        return name
    if lang == 'ar':
        return body_types_dict.get(name.lower(), pretty_en(name))
    if lang == 'en':
        return pretty_en(name)
    return _extra_dict('body_types_dict', lang).get(name.lower()) or pretty_en(name)


@register.filter(name='translate_location')
def translate_location(value, lang='ar'):
    """Translate a HappyCar Korean storage location (e.g. '전북 전주시') for
    the requested language. Korean source values render correctly in en/ar/ko;
    ru/es fall back to English transliteration. Non-Korean inputs (e.g. legacy
    pre-translated rows) pass through unchanged.
    """
    if not isinstance(value, str) or not value:
        return value
    from site_cars.happycar import locations as _locations
    return _locations.translate(value, lang)