from django.db import connection


def tenant_branding(request):
    tenant = getattr(connection, "tenant", None)
    if tenant is None:
        return {}
    return {
        "site_name": tenant.name or "سيارات",
        "site_logo": tenant.logo or "",
        "site_favicon": tenant.favicon or "",
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
    }
