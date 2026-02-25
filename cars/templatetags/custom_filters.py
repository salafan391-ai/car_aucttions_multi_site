from django import template
from cars.utils import OPTION_TRANSLATIONS, address_ar

register = template.Library()



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