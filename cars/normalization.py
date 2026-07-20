import re
"""
Canonicalization rules for car data.

Single source of truth for the synonym maps and the `normalize_name` helper
used by both the import pipeline and the one-shot normalize_car_data command.
Keep it in sync if you add new importers.
"""

BODY_SYNONYMS = {
    'pickup truck': 'truck',
}

TRANSMISSION_SYNONYMS = {
    'أوتوماتيك': 'automatic',
    'يدوي': 'manual',
    'ناقل حركة ذو تعشيق مستمر': 'cvt',
    'نصف-أوتوماتيك': 'semi-automatic',
    'آخر': 'other',
    'غير معروف': 'unknown',
}

FUEL_SYNONYMS = {}


def normalize_name(value, synonyms=None):
    """Lowercase + trim + apply synonym map. Returns None for None/empty input."""
    if value is None:
        return None
    s = value.strip() if isinstance(value, str) else value
    if not s:
        return s
    lowered = s.lower() if isinstance(s, str) else s
    if synonyms and lowered in synonyms:
        return synonyms[lowered]
    return lowered


def normalize_body(value):
    return normalize_name(value, BODY_SYNONYMS)


# Japanese feeds describe gearboxes in detail ("6at w/ manual mode (floor shift)",
# "cvt (column shift)", "5mt (floor shift)"). Collapse them to the same three
# types Korean data uses, so the filter stays usable and already-translated.
_DETAILED_TX = re.compile(r"^\d*(at|mt|cvt)\b")
_TX_BASE = {"at": "automatic", "mt": "manual", "cvt": "cvt"}


def normalize_transmission(value):
    v = normalize_name(value, TRANSMISSION_SYNONYMS)
    if isinstance(v, str):
        m = _DETAILED_TX.match(v)
        if m:
            return _TX_BASE[m.group(1)]
    return v


def normalize_fuel(value):
    return normalize_name(value, FUEL_SYNONYMS)
