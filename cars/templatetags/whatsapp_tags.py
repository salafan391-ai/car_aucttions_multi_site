import re
from django import template
from urllib.parse import quote

register = template.Library()


# Markup applied when converting AWAY from the source KRW price. KRW displays
# the original feed value; every other currency shows the price + 1%.
# Mirrors `PRICE_MARKUP` in templates/partials/lang_currency_script.html.
PRICE_MARKUP = 1.01


@register.filter
def krw_to_sar(value, rate):
    """Convert a price stored in KRW to SAR using the provided rate and
    return a formatted string with thousands separators and no decimals.

    Usage in templates:
        {{ car.price|krw_to_sar:rate_sar }}
    where `rate_sar` is exposed by the tenant context processor (SAR per 1 KRW,
    sourced from the global GlobalExchangeRates singleton).
    """
    try:
        if value is None:
            return ""
        v = float(value)
        r = float(rate) if rate is not None else 0.00250
        sar = v * r * PRICE_MARKUP
        # Format with comma as thousands separator, no decimal places
        return "{:,.0f}".format(sar)
    except Exception:
        # On any error, return an empty string to avoid breaking templates
        return ""

@register.filter
def format_whatsapp_number(phone_number):
    """
    Format phone number for WhatsApp by removing spaces, dashes, parentheses, and plus signs.
    """
    if not phone_number:
        return ""
    # Normalize and keep only ASCII digits (strip out whitespace, punctuation,
    # plus signs and any invisible/control characters like Unicode bidi marks).
    # WhatsApp expects numbers as digits with country code (no + sign), e.g. 9665...
    try:
        # Convert to string (defensive) and remove all non-digit characters
        s = str(phone_number)
        formatted = re.sub(r'[^0-9]', '', s)
        return formatted
    except Exception:
        # Fallback: original naive cleanup
        return re.sub(r'[\s\-\(\)\+]', '', str(phone_number))

@register.filter
def whatsapp_encode_text(text):
    """
    URL encode text for WhatsApp messages, including proper encoding for Arabic text.
    """
    if not text:
        return ""
    
    return quote(text, safe='')

@register.simple_tag(takes_context=True)
def whatsapp_order_message(context, car, site_name=""):
    """
    Generate a WhatsApp order-intent message (stronger than an inquiry).
    """
    message_parts = ["مرحباً، أرغب في طلب شراء السيارة التالية:"]
    message_parts.append("")

    car_name = f"{getattr(car.manufacturer, 'name_ar', None) or car.manufacturer.name} {car.model.name} {car.year}"
    message_parts.append(car_name)

    if hasattr(car, 'price') and car.price:
        # Convert stored price (KRW) to SAR using the global rate (rate_sar is per 1 KRW)
        rate_sar = None
        try:
            rate_sar = float(context.get('rate_sar'))
        except Exception:
            rate_sar = None
        if rate_sar is None:
            # fallback: read from the global singleton (shared across all tenants)
            try:
                from tenants.models import GlobalExchangeRates
                rate_sar = float(GlobalExchangeRates.get_solo().rate_sar)
            except Exception:
                rate_sar = 0.00250

        sar_price = (car.price or 0) * rate_sar * PRICE_MARKUP
        message_parts.append(f"السعر: {sar_price:,.0f} ريال")

    if hasattr(car, 'entry') and car.entry:
        message_parts.append(f"رقم الإعلان: {car.entry}")

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
    message_parts.append("أرجو التواصل لإتمام عملية الشراء.")

    if site_name:
        message_parts.append(f"شكراً - {site_name}")

    full_message = "\n".join(message_parts)
    return quote(full_message, safe='')


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
        # Convert stored price (KRW) to SAR using the global rate (rate_sar is per 1 KRW)
        rate_sar = None
        try:
            rate_sar = float(context.get('rate_sar'))
        except Exception:
            rate_sar = None
        if rate_sar is None:
            try:
                from tenants.models import GlobalExchangeRates
                rate_sar = float(GlobalExchangeRates.get_solo().rate_sar)
            except Exception:
                rate_sar = 0.00250

        sar_price = (car.price or 0) * rate_sar * PRICE_MARKUP
        message_parts.append(f"السعر: {sar_price:,.0f} ريال")

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


@register.simple_tag(takes_context=True)
def whatsapp_site_inquiry_message(context, site_name=""):
    """
    Generic WhatsApp message used outside a specific car page (footer,
    bottom nav, hero CTA). Includes the site name and the current page URL
    so the website owner knows the inquiry came from their site and is
    about cars.
    """
    parts = ["مرحباً، أود الاستفسار عن السيارات المعروضة لديكم."]

    if site_name:
        parts.append(f"الموقع: {site_name}")

    try:
        request = context.get('request')
        if request is not None:
            parts.append(f"الرابط: {request.build_absolute_uri()}")
    except Exception:
        pass

    parts.append("")
    parts.append("شكراً لكم.")

    return quote("\n".join(parts), safe='')


@register.simple_tag(takes_context=True)
def whatsapp_site_car_message(context, car, site_name=""):
    """
    Generate a WhatsApp message for a SiteCar inquiry.
    SiteCar.price is stored directly in SAR — no conversion needed.
    """
    message_parts = ["مرحباً، أرغب في الاستفسار عن السيارة التالية:"]
    message_parts.append("")

    car_name = f"{car.manufacturer} {car.model} {car.year}"
    message_parts.append(car_name)

    if car.price:
        message_parts.append(f"السعر: {car.price:,.0f} ريال سعودي")

    try:
        request = context.get('request')
        if request:
            message_parts.append("")
            message_parts.append(f"رابط السيارة: {request.build_absolute_uri()}")
    except Exception:
        pass

    message_parts.append("")
    message_parts.append("يرجى تزويدي بمزيد من المعلومات.")

    if site_name:
        message_parts.append(f"شكراً - {site_name}")

    return quote("\n".join(message_parts), safe='')