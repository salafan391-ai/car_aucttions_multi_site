from django import template
from cars.utils import OPTION_TRANSLATIONS, address_ar, car_models_dict, fuel_types_dict, transmission_types_dict, colors_dict

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





@register.filter(name='translate_model')
def translate_model(value):
    return car_models_dict.get(value, value)


@register.filter(name='translate_fuel')
def translate_fuel(value):
    return fuel_types_dict.get(value, value)



@register.filter(name='translate_transmission')
def translate_transmission(value):
    return transmission_types_dict.get(value, value)



@register.filter(name='translate_color')
def translate_color(value):
    return colors_dict.get(value, value)