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

@register.simple_tag(takes_context=True)
def whatsapp_car_message(context, car, site_name=""):
    """
    Generate a properly formatted WhatsApp message for a car inquiry,
    including a direct link to the car page.
    """
    message_parts = ["مرحباً، أرغب في الاستفسار عن السيارة التالية:"]
    message_parts.append("")

    # Car details
    car_name = f"{getattr(car.manufacturer, 'name_ar', None) or car.manufacturer.name} {car.model.name} {car.year}"
    message_parts.append(car_name)

    # Price if available
    if hasattr(car, 'price') and car.price:
        message_parts.append(f"السعر: {car.price:,.0f} ريال")

    if hasattr(car, 'entry') and car.entry:
        message_parts.append(f"رقم الإعلان: {car.entry}")

    # Car page URL
    try:
        from django.urls import reverse
        request = context.get('request')
        if car.slug:
            path = reverse('car_detail', kwargs={'slug': car.slug})
        else:
            path = reverse('car_detail_by_pk', kwargs={'pk': car.pk})
        if request:
            car_url = request.build_absolute_uri(path)
        else:
            car_url = path
        message_parts.append("")
        message_parts.append(f"رابط السيارة: {car_url}")
    except Exception:
        pass

    message_parts.append("")
    message_parts.append("يرجى تزويدي بمزيد من المعلومات.")

    if site_name:
        message_parts.append(f"شكراً - {site_name}")

    full_message = "\n".join(message_parts)
    return quote(full_message, safe='')