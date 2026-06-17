from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db import connection
from .models import Tenant, TenantPhoneNumber, TenantHeroImage
from .fonts import font_choices


@staff_member_required
def site_settings(request):
    """Site settings page for admins"""
    tenant = getattr(connection, 'tenant', None)
    
    if not tenant or tenant.schema_name == 'public':
        messages.error(request, 'لا يمكن الوصول إلى الإعدادات من النطاق العام')
        return redirect('home')
    
    if request.method == 'POST':
        # Update basic info
        tenant.name = request.POST.get('name', tenant.name)
        
        # Handle logo upload
        if 'logo' in request.FILES:
            # Delete old logo if exists
            if tenant.logo:
                tenant.logo.delete(save=False)
            tenant.logo = request.FILES['logo']
        
        # Handle favicon upload
        if 'favicon' in request.FILES:
            # Delete old favicon if exists
            if tenant.favicon:
                tenant.favicon.delete(save=False)
            tenant.favicon = request.FILES['favicon']
        
        # Handle hero image upload
        if 'hero_image' in request.FILES:
            # Delete old hero image if exists
            if tenant.hero_image:
                tenant.hero_image.delete(save=False)
            tenant.hero_image = request.FILES['hero_image']
        
        # Announcement ticker
        tenant.ticker_enabled = 'ticker_enabled' in request.POST
        tenant.ticker_text = request.POST.get('ticker_text', tenant.ticker_text)
        tenant.ticker_color = request.POST.get('ticker_color', tenant.ticker_color) or '#dc2626'

        # Update colors + site font
        tenant.site_font = request.POST.get('site_font', tenant.site_font)
        tenant.primary_color = request.POST.get('primary_color', tenant.primary_color)
        tenant.secondary_color = request.POST.get('secondary_color', tenant.secondary_color)
        tenant.accent_color = request.POST.get('accent_color', tenant.accent_color)
        
        # Update footer
        tenant.footer_text = request.POST.get('footer_text', tenant.footer_text)
        tenant.footer_text_en = request.POST.get('footer_text_en', tenant.footer_text_en)
        
        # Update business info
        tenant.tagline = request.POST.get('tagline', tenant.tagline)
        tenant.tagline_en = request.POST.get('tagline_en', tenant.tagline_en)
        tenant.about = request.POST.get('about', tenant.about)
        tenant.about_en = request.POST.get('about_en', tenant.about_en)
        tenant.seo_title = request.POST.get('seo_title', tenant.seo_title)
        tenant.seo_description = request.POST.get('seo_description', tenant.seo_description)
        tenant.seo_keywords = request.POST.get('seo_keywords', tenant.seo_keywords)
        tenant.phone = request.POST.get('phone', tenant.phone)
        tenant.phone2 = request.POST.get('phone2', tenant.phone2)
        tenant.whatsapp = request.POST.get('whatsapp', tenant.whatsapp)
        tenant.email = request.POST.get('email', tenant.email)
        tenant.address = request.POST.get('address', tenant.address)
        tenant.address_en = request.POST.get('address_en', tenant.address_en)
        tenant.city = request.POST.get('city', tenant.city)
        tenant.city_en = request.POST.get('city_en', tenant.city_en)
        tenant.map_url = request.POST.get('map_url', tenant.map_url)
        tenant.working_hours = request.POST.get('working_hours', tenant.working_hours)
        tenant.working_hours_en = request.POST.get('working_hours_en', tenant.working_hours_en)
        
        # Update contact person
        tenant.contact_person_name = request.POST.get('contact_person_name', tenant.contact_person_name)
        if 'contact_person_photo' in request.FILES:
            if tenant.contact_person_photo:
                tenant.contact_person_photo.delete(save=False)
            tenant.contact_person_photo = request.FILES['contact_person_photo']
        
        # Update social media
        tenant.instagram = request.POST.get('instagram', tenant.instagram)
        tenant.twitter = request.POST.get('twitter', tenant.twitter)
        tenant.facebook = request.POST.get('facebook', tenant.facebook)
        tenant.tiktok = request.POST.get('tiktok', tenant.tiktok)
        tenant.snapchat = request.POST.get('snapchat', tenant.snapchat)
        tenant.youtube = request.POST.get('youtube', tenant.youtube)
        
        # Update email settings
        tenant.email_host = request.POST.get('email_host', tenant.email_host)
        tenant.email_port = request.POST.get('email_port', tenant.email_port)
        tenant.email_username = request.POST.get('email_username', tenant.email_username)
        if request.POST.get('email_password'):
            tenant.email_password = request.POST.get('email_password')
        tenant.email_use_tls = 'email_use_tls' in request.POST
        tenant.email_from_name = request.POST.get('email_from_name', tenant.email_from_name)

        # Import-cost calculator settings
        tenant.import_calc_enabled = 'import_calc_enabled' in request.POST

        def _num(field, current, cast):
            raw = request.POST.get(field)
            if raw is None or str(raw).strip() == '':
                return current
            try:
                return cast(str(raw).strip())
            except (TypeError, ValueError):
                return current

        tenant.import_calc_shipping = _num('import_calc_shipping', tenant.import_calc_shipping, int)
        tenant.import_calc_shipping_small = _num('import_calc_shipping_small', tenant.import_calc_shipping_small, int)
        tenant.import_calc_shipping_large = _num('import_calc_shipping_large', tenant.import_calc_shipping_large, int)
        tenant.import_calc_duty_pct = _num('import_calc_duty_pct', tenant.import_calc_duty_pct, float)
        tenant.import_calc_vat_pct = _num('import_calc_vat_pct', tenant.import_calc_vat_pct, float)
        tenant.import_calc_clearance = _num('import_calc_clearance', tenant.import_calc_clearance, int)
        tenant.import_calc_inspection = _num('import_calc_inspection', tenant.import_calc_inspection, int)
        tenant.import_calc_registration = _num('import_calc_registration', tenant.import_calc_registration, int)
        tenant.import_calc_agent = _num('import_calc_agent', tenant.import_calc_agent, int)
        tenant.import_calc_preyear = _num('import_calc_preyear', tenant.import_calc_preyear, int)
        tenant.import_calc_preyear_extra = _num('import_calc_preyear_extra', tenant.import_calc_preyear_extra, int)

        # Extra destination countries (repeatable rows -> JSON list)
        _c_names = request.POST.getlist('c_name_ar[]')
        if _c_names is not None:
            _c_en = request.POST.getlist('c_name_en[]')
            _c_flag = request.POST.getlist('c_flag[]')
            _c_cur = request.POST.getlist('c_currency[]')

            def _carr(n):
                return request.POST.getlist(n + '[]')

            def _at(lst, i, cast, default=0):
                try:
                    v = lst[i]
                    return cast(v) if str(v).strip() != '' else default
                except (IndexError, ValueError, TypeError):
                    return default

            _ship_s, _ship_m, _ship_l = _carr('c_shipping_small'), _carr('c_shipping_medium'), _carr('c_shipping_large')
            _duty, _vat = _carr('c_duty_pct'), _carr('c_vat_pct')
            _clr, _insp, _reg, _ag = _carr('c_clearance'), _carr('c_inspection'), _carr('c_registration'), _carr('c_agent')
            _py, _pye = _carr('c_preyear'), _carr('c_preyear_extra')
            _countries = []
            for i, nm in enumerate(_c_names):
                if not (nm or '').strip():
                    continue
                _countries.append({
                    'name_ar': nm.strip(),
                    'name_en': (_c_en[i].strip() if i < len(_c_en) else ''),
                    'flag': (_c_flag[i].strip() if i < len(_c_flag) else ''),
                    'currency': (_c_cur[i].strip() if i < len(_c_cur) and _c_cur[i] else 'SAR'),
                    'shipping_small': _at(_ship_s, i, int), 'shipping_medium': _at(_ship_m, i, int), 'shipping_large': _at(_ship_l, i, int),
                    'duty_pct': _at(_duty, i, float), 'vat_pct': _at(_vat, i, float),
                    'clearance': _at(_clr, i, int), 'inspection': _at(_insp, i, int),
                    'registration': _at(_reg, i, int), 'agent': _at(_ag, i, int),
                    'preyear': _at(_py, i, int), 'preyear_extra': _at(_pye, i, int),
                })
            tenant.import_calc_countries = _countries

        tenant.save()
        
        # Handle multiple phone numbers
        # First, handle deletions
        existing_phone_ids = request.POST.getlist('phone_id[]')
        # Filter out empty strings and convert to integers
        valid_phone_ids = [int(pid) for pid in existing_phone_ids if pid.strip() and pid.isdigit()]
        
        if valid_phone_ids:
            # Delete phone numbers not in the submitted list
            tenant.phone_numbers.exclude(id__in=valid_phone_ids).delete()
        else:
            # If no valid phone IDs, delete all
            tenant.phone_numbers.all().delete()
        
        # Update or create phone numbers
        phone_numbers = request.POST.getlist('phone_number[]')
        phone_types = request.POST.getlist('phone_type[]')
        phone_labels = request.POST.getlist('phone_label[]')
        phone_primaries = request.POST.getlist('phone_primary[]')
        
        for i, phone in enumerate(phone_numbers):
            if phone.strip():  # Only save non-empty phone numbers
                phone_type = phone_types[i] if i < len(phone_types) else 'general'
                phone_label = phone_labels[i] if i < len(phone_labels) else ''
                is_primary = str(i) in phone_primaries
                
                # Check if this is an existing phone (has ID)
                if i < len(existing_phone_ids) and existing_phone_ids[i] and existing_phone_ids[i].isdigit():
                    # Update existing
                    try:
                        phone_obj = TenantPhoneNumber.objects.get(id=existing_phone_ids[i], tenant=tenant)
                        phone_obj.phone_number = phone
                        phone_obj.phone_type = phone_type
                        phone_obj.label = phone_label
                        phone_obj.is_primary = is_primary
                        phone_obj.order = i
                        phone_obj.save()
                    except TenantPhoneNumber.DoesNotExist:
                        pass
                else:
                    # Create new
                    TenantPhoneNumber.objects.create(
                        tenant=tenant,
                        phone_number=phone,
                        phone_type=phone_type,
                        label=phone_label,
                        is_primary=is_primary,
                        order=i
                    )
        
        # Handle hero images: delete requested ones
        delete_hero_ids = request.POST.getlist('delete_hero_image[]')
        if delete_hero_ids:
            for hero_id in delete_hero_ids:
                try:
                    hero_obj = TenantHeroImage.objects.get(id=hero_id, tenant=tenant)
                    hero_obj.image.delete(save=False)
                    hero_obj.delete()
                except TenantHeroImage.DoesNotExist:
                    pass

        # Update order of existing hero images
        hero_orders = request.POST.getlist('hero_image_order[]')
        hero_ids = request.POST.getlist('hero_image_id[]')
        for hero_id, order_val in zip(hero_ids, hero_orders):
            try:
                TenantHeroImage.objects.filter(id=hero_id, tenant=tenant).update(order=int(order_val))
            except (ValueError, TenantHeroImage.DoesNotExist):
                pass

        # Add new hero images
        new_hero_images = request.FILES.getlist('new_hero_images[]')
        existing_count = tenant.hero_images.count()
        for i, img_file in enumerate(new_hero_images):
            TenantHeroImage.objects.create(
                tenant=tenant,
                image=img_file,
                order=existing_count + i
            )

        messages.success(request, 'تم حفظ الإعدادات بنجاح!')
        # Bust tenant branding cache so new rates take effect immediately
        from django.core.cache import cache as _cache
        _schema = getattr(connection, 'schema_name', 'public')
        _cache.delete(f"tenant_branding:{_schema}")
        return redirect('site_settings')
    
    context = {
        'tenant': tenant,
        'phone_numbers': tenant.phone_numbers.all(),
        'phone_types': TenantPhoneNumber.PHONE_TYPES,
        'hero_images': tenant.hero_images.all(),
        'site_font_choices': font_choices(),
    }
    return render(request, 'tenants/site_settings.html', context)
