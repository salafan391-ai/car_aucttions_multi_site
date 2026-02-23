from urllib.parse import quote_plus

from django import template

register = template.Library()


@register.filter(is_safe=True)
def qs_value(value, maxlen=200):
    """Encode a querystring value safely and truncate to maxlen characters.

    - Ensures special characters (slashes, ampersands) are percent-encoded.
    - Truncates very long values to avoid huge responses caused by malicious
      or malformed querystrings.

    Usage in templates: {{ v|qs_value }}
    """
    try:
        s = str(value)
    except Exception:
        return ""
    try:
        maxlen = int(maxlen)
    except Exception:
        maxlen = 200
    if len(s) > maxlen:
        s = s[:maxlen]
    # quote_plus makes spaces '+', which is fine for querystrings
    return quote_plus(s)
