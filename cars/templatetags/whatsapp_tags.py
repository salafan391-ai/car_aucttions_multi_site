import re
from django import template
from urllib.parse import quote

register = template.Library()

@register.filter
def format_whatsapp_number(phone_number):
    """
    Format phone number for WhatsApp by removing spaces, dashes, parentheses, and plus signs.
    """
    if not phone_number:
        return ""
    
    # Remove spaces, dashes, parentheses, and plus signs
    formatted = re.sub(r'[\s\-\(\)\+]', '', phone_number)
    return formatted

@register.filter
def whatsapp_encode_text(text):
    """
    URL encode text for WhatsApp messages, including proper encoding for Arabic text.
    """
    if not text:
        return ""
    
    return quote(text, safe='')

@register.simple_tag
def whatsapp_car_message(car, site_name=""):
    """
    Generate a properly formatted WhatsApp message for a car inquiry.
    """
    message_parts = ["مرحباً، أرغب في الاستفسار عن السيارة التالية:"]
    message_parts.append("")
    
    # Car details
    car_name = f"{getattr(car.manufacturer, 'name_ar', car.manufacturer.name) or car.manufacturer.name} {car.model.name} {car.year}"
    message_parts.append(car_name)
    
    # Price if available
    if hasattr(car, 'price') and car.price:
        message_parts.append(f"السعر: {car.price:,.0f} ريال")
    
    # Lot number if available
    if hasattr(car, 'lot_number') and car.lot_number:
        message_parts.append(f"رقم القطعة: {car.lot_number}")
    
    # VIN if available
    if hasattr(car, 'vin') and car.vin:
        message_parts.append(f"رقم الهيكل: {car.vin}")
    
    message_parts.append("")
    message_parts.append("يرجى تزويدي بمزيد من المعلومات.")
    
    if site_name:
        message_parts.append(f"شكراً - {site_name}")
    
    full_message = "\n".join(message_parts)
    return quote(full_message, safe='')