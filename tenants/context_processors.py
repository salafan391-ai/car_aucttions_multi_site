from django.db import connection


def tenant_branding(request):
    tenant = getattr(connection, "tenant", None)
    if tenant is None:
        return {}
    
    # Get all phone numbers for the tenant
    phone_numbers = []
    if hasattr(tenant, 'phone_numbers'):
        phone_numbers = tenant.phone_numbers.filter(is_active=True).order_by('order', '-is_primary')
    
    # Get primary phone number
    primary_phone = None
    if phone_numbers:
        primary_phone = next((p for p in phone_numbers if p.is_primary), phone_numbers[0] if phone_numbers else None)
    
    # Get sales phone numbers
    sales_phones = [p for p in phone_numbers if p.phone_type == 'sales']
    
    # Get WhatsApp phone numbers
    whatsapp_phones = [p for p in phone_numbers if p.phone_type == 'whatsapp']
    
    return {
        "site_name": tenant.name or "سيارات",
        "site_logo": tenant.logo.url if tenant.logo else "",
        "site_favicon": tenant.favicon.url if tenant.favicon else "",
        "site_hero_image": tenant.hero_image.url if tenant.hero_image else "",
        "primary_color": tenant.primary_color or "#2563eb",
        "secondary_color": tenant.secondary_color or "#1e3a8a",
        "accent_color": tenant.accent_color or "#3b82f6",
        "footer_text": tenant.footer_text or "",
        "footer_text_en": tenant.footer_text_en or "",
        # Business info
        "site_about": tenant.about or "",
        "site_about_en": tenant.about_en or "",
        "site_phone": tenant.phone or "",
        "site_phone2": tenant.phone2 or "",
        "site_whatsapp": tenant.whatsapp or "",
        "site_email": tenant.email or "",
        "site_address": tenant.address or "",
        "site_address_en": tenant.address_en or "",
        "site_city": tenant.city or "",
        "site_city_en": tenant.city_en or "",
        "site_map_url": tenant.map_url or "",
        "site_working_hours": tenant.working_hours or "",
        "site_working_hours_en": tenant.working_hours_en or "",
        # Contact person
        "contact_person_name": tenant.contact_person_name or "",
        "contact_person_photo": tenant.contact_person_photo.url if tenant.contact_person_photo else "",
        # Social media
        "site_instagram": tenant.instagram or "",
        "site_twitter": tenant.twitter or "",
        "site_facebook": tenant.facebook or "",
        "site_tiktok": tenant.tiktok or "",
        "site_snapchat": tenant.snapchat or "",
        "site_youtube": tenant.youtube or "",
        # Multiple phone numbers
        "phone_numbers": phone_numbers,
        "primary_phone": primary_phone,
        "sales_phones": sales_phones,
        "whatsapp_phones": whatsapp_phones,
    }
