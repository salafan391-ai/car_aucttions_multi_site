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


@register.simple_tag(takes_context=True)
def absolute_url(context, url):
    """Return an absolute https URL. Pass through if already absolute, else prepend
    the current request's scheme + host. Used for og:image / twitter:image meta
    tags where social-link scrapers (WhatsApp, Twitter) need a fetchable URL."""
    if not url:
        return ''
    s = str(url)
    if s.startswith(('http://', 'https://')):
        return _force_https(s)
    request = context.get('request')
    if request is not None:
        return request.build_absolute_uri(s)
    return s


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


# Icon SVGs (24x24 viewBox, stroke="currentColor"). Picked from Heroicons-style
# vocabulary; the mapping below assigns one to each Encar option code.
_OPTION_ICON_SVGS = {
    'shield': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 3v6c0 4.5-3.4 8.4-8 9-4.6-.6-8-4.5-8-9V6l8-3z"/><path d="M9.5 12.5l2 2 3.5-4"/></svg>',
    'seat': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 4h6a3 3 0 013 3v6h-6a3 3 0 01-3-3V4z"/><path d="M5 13h11v4a3 3 0 01-3 3H8a3 3 0 01-3-3v-4z"/><path d="M16 9h2a2 2 0 012 2v3"/></svg>',
    'flame': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3s4 4 4 8a4 4 0 11-8 0c0-2 1-3 1-3s-2 1-2 4a6 6 0 0012 0c0-5-7-9-7-9z"/></svg>',
    'fan': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="2"/><path d="M12 10c0-3 1.5-6 4.5-6 1.5 0 2.5 1 2.5 2.5 0 3-3 4.5-7 4.5z"/><path d="M14 12c3 0 6 1.5 6 4.5 0 1.5-1 2.5-2.5 2.5-3 0-4.5-3-4.5-7z"/><path d="M12 14c0 3-1.5 6-4.5 6C6 20 5 19 5 17.5c0-3 3-4.5 7-4.5z"/><path d="M10 12c-3 0-6-1.5-6-4.5C4 6 5 5 6.5 5c3 0 4.5 3 4.5 7z"/></svg>',
    'snowflake': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v20M2 12h20M5 5l14 14M19 5L5 19"/></svg>',
    'lock': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="1.5"/><path d="M8 11V7a4 4 0 018 0v4"/></svg>',
    'key': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="14" r="4"/><path d="M11 12l9-9M16 8l3 3"/></svg>',
    'wireless': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9c5-5 13-5 18 0M6 12c3.5-3.5 9-3.5 12 0M9 15a4 4 0 016 0"/><circle cx="12" cy="19" r="1.2"/></svg>',
    'mirror': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 6h14l-2 8H7L5 6z"/><path d="M9 14v5h6v-5"/></svg>',
    'camera': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7l1.5-3h3L15 7"/><circle cx="12" cy="13.5" r="3.5"/></svg>',
    'around': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3"/></svg>',
    'sensor': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 16c2.5-2.5 6-4 9-4s6.5 1.5 9 4"/><path d="M6 13c2-2 4-3 6-3s4 1 6 3"/><circle cx="12" cy="17" r="1.2"/></svg>',
    'tpms': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8"/><path d="M12 8v4l2.5 2.5"/><circle cx="18" cy="18" r="1.2"/></svg>',
    'wheel': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2"/><path d="M12 3v6M12 21v-6M3 12h6M21 12h-6"/></svg>',
    'steering': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/><path d="M12 9.5V3M9.5 14.5L4 18M14.5 14.5L20 18"/></svg>',
    'paddle': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 6h14M7 6v12M17 6v12M5 18h14"/><circle cx="12" cy="12" r="2"/></svg>',
    'brake': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M9 8h3a2.5 2.5 0 010 5h-3v4M9 8v9"/></svg>',
    'cruise': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 13a9 9 0 10-18 0"/><path d="M12 13l4-4"/><circle cx="12" cy="13" r="1"/></svg>',
    'lightbulb': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6M10 21h4M9 14a5 5 0 116 0v2H9v-2z"/></svg>',
    'sun': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/></svg>',
    'window': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="5" width="16" height="14" rx="1"/><path d="M4 12h16M12 5v14"/></svg>',
    'door': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 21V4a1 1 0 011-1h10a1 1 0 011 1v17"/><path d="M4 21h16"/><circle cx="15" cy="13" r="0.8"/></svg>',
    'curtain': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16M5 4c0 8 2 14 5 16M19 4c0 8-2 14-5 16M9 4c1 7 1 14 0 16M15 4c-1 7-1 14 0 16"/></svg>',
    'trunk': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 18V8a4 4 0 014-4h8a4 4 0 014 4v10"/><path d="M2 18h20M8 13h8"/></svg>',
    'rack': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h18M3 11h18M3 14h18M5 8V6M19 8V6M5 14v2M19 14v2"/></svg>',
    'tv': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="12" rx="1.5"/><path d="M8 21h8M12 17v4"/></svg>',
    'disc': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="0.8" fill="currentColor"/></svg>',
    'plug': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3v6M15 3v6"/><rect x="6" y="9" width="12" height="6" rx="1"/><path d="M12 15v3a3 3 0 003 3"/></svg>',
    'usb': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="20" r="2"/><path d="M12 18V8M12 8l-3 3M12 8l3 3"/><path d="M9 14h2v3M15 12h-2v5"/></svg>',
    'bluetooth': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M7 7l10 10-5 5V2l5 5L7 17"/></svg>',
    'map': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3V6z"/><path d="M9 3v15M15 6v15"/></svg>',
    'rain': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M7 13a4 4 0 011-7.9 5 5 0 019.9 1.1A4 4 0 0117 13H7z"/><path d="M9 17l-1 3M13 17l-1 3M17 17l-1 3"/></svg>',
    'lane': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4l4 17M19 4l-4 17M11 6v3M11 13v3M11 20v0"/></svg>',
    'bell': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 18h12l-1.5-2V11a4.5 4.5 0 10-9 0v5L6 18z"/><path d="M10 20a2 2 0 004 0"/></svg>',
    'massage': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h2M9 9h2M9 15h2M13 7h2M13 17h2M17 12h2"/><path d="M3 12h2M19 12h2"/></svg>',
    'hud': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="9" rx="1.5"/><path d="M8 10h2M14 10h2M9 13h6"/><path d="M5 18l-1 2M19 18l1 2"/></svg>',
    'toll': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11h18M5 11v9h14v-9M5 11l7-7 7 7"/><path d="M11 14h2v3h-2z"/></svg>',
    'memory': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M7 4h10v17l-5-3-5 3V4z"/></svg>',
    'sparkle': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.7 4.3L18 9l-4.3 1.7L12 15l-1.7-4.3L6 9l4.3-1.7L12 3z"/><path d="M19 16l1 2 2 1-2 1-1 2-1-2-2-1 2-1 1-2z"/></svg>',
    'check': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8.5 12.5l2.5 2.5L15.5 9.5"/></svg>',
}

# Each Encar option code → icon key. Anything not listed falls back to "check".
_OPTION_ICON_MAP = {
    '001': 'brake',     # ABS
    '002': 'shield',    # ECS
    '003': 'disc',      # CD player
    '004': 'tv',        # Front AV monitor
    '005': 'map',       # Navigation
    '006': 'lock',      # Power door lock
    '007': 'window',    # Power Windows
    '008': 'steering',  # Power steering wheel
    '010': 'sun',       # Sunroof
    '014': 'seat',      # Leather seat
    '015': 'wireless',  # Wireless door lock
    '017': 'wheel',     # Aluminum wheel
    '019': 'shield',    # TCS Anti-slip
    '020': 'shield',    # Side airbag
    '021': 'seat',      # Electric driver seat
    '022': 'flame',     # Heated front seats
    '023': 'snowflake', # Auto AC
    '024': 'mirror',    # Electric folding mirrors
    '026': 'shield',    # Driver airbag
    '027': 'shield',    # Passenger airbag
    '029': 'flame',     # Heated steering
    '030': 'mirror',    # ECM mirror
    '031': 'steering',  # Steering wheel remote
    '032': 'sensor',    # Rear parking sensor
    '033': 'tpms',      # TPMS
    '034': 'fan',       # Vent driver seat
    '035': 'seat',      # Electric passenger seat
    '051': 'memory',    # Memory driver seat
    '054': 'tv',        # Rear AV monitor
    '055': 'shield',    # ESC
    '056': 'shield',    # Curtain airbag
    '057': 'key',       # Smart key
    '058': 'camera',    # Rear camera
    '059': 'trunk',     # Power trunk
    '062': 'rack',      # Roof rack
    '063': 'flame',     # Rear heated seats
    '068': 'cruise',    # Cruise control
    '071': 'plug',      # AUX
    '072': 'usb',       # USB
    '074': 'toll',      # High pass
    '075': 'lightbulb', # LED Headlamp
    '077': 'fan',       # Vent passenger seat
    '078': 'memory',    # Memory passenger seat
    '079': 'cruise',    # Adaptive cruise
    '080': 'door',      # Ghost door closing
    '081': 'rain',      # Rain sensor
    '082': 'flame',     # Thermal steering
    '083': 'steering',  # Electric steering
    '084': 'paddle',    # Paddle shift
    '085': 'sensor',    # Front parking sensor
    '086': 'bell',      # Rear alarm
    '087': 'around',    # 360 view
    '088': 'lane',      # Lane departure
    '089': 'seat',      # Rear electric seat
    '090': 'fan',       # Rear vent seat
    '091': 'massage',   # Massage seat
    '092': 'curtain',   # Rear curtain
    '093': 'curtain',   # Rear blind
    '094': 'brake',     # EPB
    '095': 'hud',       # HUD
    '096': 'bluetooth', # Bluetooth
    '097': 'lightbulb', # Auto light
}


@register.filter
def option_icon(value):
    """Inline SVG icon for an Encar option code (e.g. '001' → ABS shield)."""
    key = _OPTION_ICON_MAP.get(str(value).strip(), 'check')
    return _OPTION_ICON_SVGS.get(key, _OPTION_ICON_SVGS['check'])



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


# Map every known color name (Arabic or English, lowercased) to a CSS color
# string. Two-tone variants return a 50/50 linear gradient. Returns the
# fallback `#9ca3af` (gray-400) for unknown names so the swatch always renders.
_COLOR_HEX = {
    # Singletons (English)
    "black": "#0a0a0a",
    "white": "#fafafa",
    "silver": "#bfbfbf",
    "bright silver": "#d6d6d6",
    "silver metallic": "#bcc1c5",
    "silver gray": "#a8acaf",
    "silent silver": "#c0c2c4",
    "galaxy silver": "#5b6770",
    "gray": "#7a7d80",
    "dark gray": "#3f4448",
    "space gray": "#525960",
    "platinum": "#d9d9d6",
    "gold": "#c9a45a",
    "light gold": "#dcc581",
    "blue": "#2563eb",
    "sky blue": "#7fb6ff",
    "dark blue": "#1e3a8a",
    "cosmic blue": "#0b1d52",
    "mercury blue": "#445a86",
    "red": "#dc2626",
    "burgundy": "#6d1b25",
    "maroon": "#8a2331",
    "marsala": "#964f4c",
    "cherry": "#a01d2b",
    "green": "#16a34a",
    "light green": "#86efac",
    "lime green": "#a3e635",
    "yellow green": "#bef264",
    "storr green": "#3a6b3a",
    "yellow": "#facc15",
    "sunflower": "#f5c518",
    "orange": "#f97316",
    "orange pop": "#ff7a18",
    "copper": "#b87333",
    "bronze": "#8c6232",
    "brown": "#7a4a2a",
    "reed brown": "#7a5230",
    "beige": "#e6d8b8",
    "creamy beige": "#ead9b8",
    "creamy": "#f4e8d0",
    "vanilla": "#f3e5ab",
    "ivory": "#f6f0d8",
    "purple": "#7c3aed",
    "pink": "#ec4899",
    "turquoise": "#14b8a6",
    "teal": "#0d9488",
    "metallic": "#9ca3af",
    "pearl": "#ece4d3",
    "pearl white": "#f4ecdc",
    "black pearl": "#171314",
    # Singletons (Arabic)
    "أسود": "#0a0a0a", "اسود": "#0a0a0a", "سوداء": "#0a0a0a",
    "أبيض": "#fafafa",
    "فضي": "#bfbfbf", "الفضي": "#bfbfbf",
    "رمادي": "#7a7d80",
    "ذهبي": "#c9a45a",
    "أزرق": "#2563eb", "ازرق": "#2563eb", "الأزرق": "#2563eb",
    "أزرق سماوي": "#7fb6ff",
    "أزرق داكن": "#1e3a8a",
    "أحمر": "#dc2626", "الأحمر": "#dc2626",
    "أحمر بورجوندي": "#6d1b25",
    "بورغندي": "#6d1b25",
    "كرزي": "#a01d2b",
    "أخضر": "#16a34a", "الأخضر": "#16a34a",
    "أخضر فاتح": "#86efac",
    "أخضر ليموني": "#a3e635",
    "أصفر": "#facc15",
    "برتقالي": "#f97316",
    "بني": "#7a4a2a",
    "بني قصب": "#7a5230",
    "بيج": "#e6d8b8",
    "كريمي": "#f4e8d0",
    "بنفسجي": "#7c3aed",
    "وردي": "#ec4899",
    "فيروزي": "#14b8a6",
    "لؤلؤي": "#ece4d3",
    "أبيض لؤلؤي": "#f4ecdc",
    "بلاتيني": "#d9d9d6",
    "ذهبي فاتح": "#dcc581",
    "فضي فاتح": "#d6d6d6",
    "فضي معدني": "#bcc1c5",
    "فضي رمادي": "#a8acaf",
    "فضي جالاكسي": "#5b6770",
    "رمادي داكن": "#3f4448",
    "مارون": "#8a2331",
    "مارسالا": "#964f4c",
    "معدني": "#9ca3af",
    "عاجي": "#f6f0d8",
    "فانيليا": "#f3e5ab",
    "غير محدد": "#9ca3af", "unspecified": "#9ca3af", "etc": "#9ca3af", "기타": "#9ca3af",
}

# For two-tone colors we render a 50/50 split between the dominant color and
# its pairing. The leading word picks the colour; "two-tone" pairs with white.
_TWO_TONE_PARTNER_EN = {
    "black": "#fafafa",   # black + white
    "white": "#0a0a0a",   # white + black
    "silver": "#0a0a0a",  # silver + black
    "gold":   "#0a0a0a",
    "pearl":  "#0a0a0a",
    "brown":  "#e6d8b8",  # brown + beige
}
_TWO_TONE_PARTNER_AR = {
    "أسود": "#fafafa",
    "أبيض": "#0a0a0a",
    "فضي":  "#0a0a0a",
    "ذهبي": "#0a0a0a",
    "لؤلؤي": "#0a0a0a",
    "بني":  "#e6d8b8",
}


@register.filter(name='color_to_css')
def color_to_css(value):
    """Return a CSS color (or linear-gradient) for a CarColor name. Used to
    render a small color swatch beside the color filter chip. Falls back to
    a neutral gray when the name is unknown so the swatch always shows."""
    if value is None:
        return "#9ca3af"
    name = getattr(value, 'name', value)
    if not isinstance(name, str):
        return "#9ca3af"
    key = name.strip().lower()

    # Two-tone in English ("black two-tone", "pearl two-tone", …)
    if "two-tone" in key:
        base_word = key.replace("two-tone", "").strip()
        base = _COLOR_HEX.get(base_word)
        partner = _TWO_TONE_PARTNER_EN.get(base_word, "#fafafa")
        if base:
            return f"linear-gradient(135deg, {base} 50%, {partner} 50%)"

    # Two-tone in Arabic ("أسود ثنائي اللون", …)
    if "ثنائي اللون" in name:
        base_word = name.replace("ثنائي اللون", "").strip()
        base = _COLOR_HEX.get(base_word)
        partner = _TWO_TONE_PARTNER_AR.get(base_word, "#fafafa")
        if base:
            return f"linear-gradient(135deg, {base} 50%, {partner} 50%)"

    return _COLOR_HEX.get(key, _COLOR_HEX.get(name.strip(), "#9ca3af"))


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