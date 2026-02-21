from django import template
from cars.utils import OPTION_TRANSLATIONS

register = template.Library()



@register.filter
def translate_option(value):
    """
    Translates a given option value using the OPTION_TRANSLATIONS mapping.
    If the value is not found in the mapping, it returns the original value.
    """
    return OPTION_TRANSLATIONS.get('ar', {}).get(value, value)