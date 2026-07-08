from django.shortcuts import render, redirect
from django.urls import reverse, NoReverseMatch
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.db import connection
from .models import Tenant, TenantPhoneNumber, TenantHeroImage, TenantWorkStep, TenantSalesPerson
from .fonts import font_choices


@staff_member_required
def set_dashboard_password(request):
    """Let a tenant owner set a password for their dashboard account, so they
    can log in directly at /login/ (not only via the pdf_export SSO auto-login)."""
    tenant = getattr(connection, 'tenant', None)
    if not tenant or tenant.schema_name == 'public':
        messages.error(request, 'غير متاح من النطاق العام')
        return redirect('home')
    if request.method == 'POST':
        p1 = request.POST.get('new_password1') or ''
        p2 = request.POST.get('new_password2') or ''
        errors = []
        if not p1:
            errors.append('كلمة المرور مطلوبة.')
        if p1 != p2:
            errors.append('كلمتا المرور غير متطابقتين.')
        try:
            validate_password(p1, user=request.user)
        except ValidationError as e:
            errors.extend(e.messages)
        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            request.user.set_password(p1)
            request.user.save(update_fields=['password'])
            update_session_auth_hash(request, request.user)  # stay logged in
            messages.success(
                request,
                f'تم تعيين كلمة المرور. يمكنك الآن الدخول مباشرة باسم المستخدم «{request.user.username}» وكلمة المرور.',
            )
    return redirect('site_settings')


def friendly_page_links():
    """Friendly site pages → their URLs, for link-picker dropdowns."""
    pages = [
        ("الرئيسية", "home", ""),
        ("السيارات", "car_list", ""),
        ("المزادات", "car_list", "?car_type=auction"),
        ("قطع الغيار", "parts_list", ""),
        ("الإكسسوارات", "accessories_list", ""),
        ("المفضلة", "wishlist", ""),
        ("تواصل معنا", "contact", ""),
    ]
    links = []
    for label, name, suffix in pages:
        try:
            links.append({"label": label, "url": reverse(name) + suffix})
        except NoReverseMatch:
            continue
    return links


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

        # "How we work" section
        tenant.show_how_we_work = 'show_how_we_work' in request.POST
        tenant.how_we_work_title = request.POST.get('how_we_work_title', tenant.how_we_work_title)

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

        # Update commercial registration (السجل التجاري)
        tenant.commercial_registration = request.POST.get('commercial_registration', tenant.commercial_registration)
        if request.POST.get('cr_barcode_clear') == '1' and tenant.cr_barcode:
            tenant.cr_barcode.delete(save=False)
            tenant.cr_barcode = None
        if 'cr_barcode' in request.FILES:
            if tenant.cr_barcode:
                tenant.cr_barcode.delete(save=False)
            tenant.cr_barcode = request.FILES['cr_barcode']

        # Update social media
        tenant.instagram = request.POST.get('instagram', tenant.instagram)
        tenant.twitter = request.POST.get('twitter', tenant.twitter)
        tenant.facebook = request.POST.get('facebook', tenant.facebook)
        tenant.tiktok = request.POST.get('tiktok', tenant.tiktok)
        tenant.snapchat = request.POST.get('snapchat', tenant.snapchat)
        tenant.youtube = request.POST.get('youtube', tenant.youtube)
        tenant.telegram = request.POST.get('telegram', tenant.telegram)
        tenant.telegram_username = request.POST.get('telegram_username', tenant.telegram_username)
        tenant.whatsapp_channel = request.POST.get('whatsapp_channel', tenant.whatsapp_channel)

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

        # ── Buyer contract (عقد وساطة) ──
        tenant.contract_enabled = 'contract_enabled' in request.POST
        tenant.contract_party1 = request.POST.get('contract_party1', tenant.contract_party1)
        tenant.contract_bank = request.POST.get('contract_bank', tenant.contract_bank)
        tenant.contract_commission = request.POST.get('contract_commission', tenant.contract_commission)
        tenant.contract_clearance_org = request.POST.get('contract_clearance_org', tenant.contract_clearance_org)
        tenant.contract_clearance_license = request.POST.get('contract_clearance_license', tenant.contract_clearance_license)
        tenant.contract_default_region = request.POST.get('contract_default_region', tenant.contract_default_region)
        tenant.contract_default_port = request.POST.get('contract_default_port', tenant.contract_default_port)
        tenant.contract_import_days = request.POST.get('contract_import_days', tenant.contract_import_days)
        tenant.contract_phone = request.POST.get('contract_phone', tenant.contract_phone)
        tenant.contract_email = request.POST.get('contract_email', tenant.contract_email)
        if request.POST.get('contract_stamp_clear') and tenant.contract_stamp:
            tenant.contract_stamp.delete(save=False)
            tenant.contract_stamp = None
        if 'contract_stamp' in request.FILES:
            if tenant.contract_stamp:
                tenant.contract_stamp.delete(save=False)
            tenant.contract_stamp = request.FILES['contract_stamp']

        # ── Catalog filter (which shared auction/encar cars show on this site) ──
        def _posint(name):
            v = (request.POST.get(name) or '').strip()
            return int(v) if v.isdigit() else None
        _panel_set = {
            'left_front_fender', 'right_front_fender', 'hood_front', 'trunk_lid',
            'right_rear_door', 'right_front_door', 'left_front_door', 'left_rear_door',
            'rear_member', 'right_rear_quarter', 'center_floor', 'left_rear_quarter',
            'front_member', 'rear_floor', 'roof',
        }
        def _rules(prefix):
            return {
                'year_min': _posint(f'catalog_{prefix}_year_min'),
                'year_max': _posint(f'catalog_{prefix}_year_max'),
                'price_min': _posint(f'catalog_{prefix}_price_min'),
                'price_max': _posint(f'catalog_{prefix}_price_max'),
                'makes': [int(x) for x in request.POST.getlist(f'catalog_{prefix}_makes') if x.isdigit()],
                'models': [int(x) for x in request.POST.getlist(f'catalog_{prefix}_models') if x.isdigit()],
                'exclude_types': [t for t in request.POST.getlist(f'catalog_{prefix}_exclude_types') if t in ('replaced', 'painted')],
                'exclude_panels': [p for p in request.POST.getlist(f'catalog_{prefix}_exclude_panels') if p in _panel_set],
            }
        tenant.catalog_filter = {'auction': _rules('auction'), 'encar': _rules('encar')}
        _catalog_changed = tenant.catalog_filter != (tenant.__class__.objects
                                                      .filter(pk=tenant.pk)
                                                      .values_list('catalog_filter', flat=True).first() or {})

        # ── Site theme (admin-selectable subset) ──
        _theme_before = tenant.template_theme
        _chosen_theme = request.POST.get('template_theme', '')
        if _chosen_theme in ('default', 'glassy', 'modern'):
            tenant.template_theme = _chosen_theme
        _theme_changed = tenant.template_theme != _theme_before

        # ── Landing page (enable/disable + design) ──
        _landing_before = (tenant.landing_is_active, tenant.landing_design)
        tenant.landing_is_active = 'landing_is_active' in request.POST
        _ld = request.POST.get('landing_design', '')
        if _ld in dict(tenant.LANDING_DESIGN_CHOICES):
            tenant.landing_design = _ld
        _landing_changed = (tenant.landing_is_active, tenant.landing_design) != _landing_before

        tenant.save()

        # Catalog-surface cache keys embed a filter signature, so brand-new filter
        # values recompute automatically. Reverting to a *previously used* value
        # would hit its old cached page until TTL — so on any change, drop this
        # tenant's cached car pages (keys are namespaced by its schema name).
        if _catalog_changed or _theme_changed or _landing_changed:
            try:
                from django.core.cache import cache as _cache
                if hasattr(_cache, 'delete_pattern'):
                    _cache.delete_pattern(f"*{tenant.schema_name}*")
            except Exception:
                pass
        
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

        # ── Salespeople (repeatable, each with optional photo) ──
        sp_ids = request.POST.getlist('salesperson_id[]')
        sp_names = request.POST.getlist('salesperson_name[]')
        sp_roles = request.POST.getlist('salesperson_role[]')
        sp_whatsapps = request.POST.getlist('salesperson_whatsapp[]')
        sp_phones = request.POST.getlist('salesperson_phone[]')
        sp_rowkeys = request.POST.getlist('salesperson_rowkey[]')

        # Delete salespeople whose row was removed from the form.
        kept_ids = [int(i) for i in sp_ids if i.strip().isdigit()]
        if kept_ids:
            tenant.sales_people.exclude(id__in=kept_ids).delete()
        elif not sp_names:
            tenant.sales_people.all().delete()

        for i, name in enumerate(sp_names):
            name = name.strip()
            if not name:
                continue
            rowkey = sp_rowkeys[i] if i < len(sp_rowkeys) else str(i)
            photo = request.FILES.get(f'salesperson_photo_{rowkey}')
            role = sp_roles[i] if i < len(sp_roles) else ''
            whatsapp = sp_whatsapps[i] if i < len(sp_whatsapps) else ''
            phone = sp_phones[i] if i < len(sp_phones) else ''
            existing_id = sp_ids[i] if i < len(sp_ids) else ''

            if existing_id and existing_id.strip().isdigit():
                try:
                    sp = tenant.sales_people.get(id=int(existing_id))
                except TenantSalesPerson.DoesNotExist:
                    continue
                sp.name, sp.role, sp.whatsapp, sp.phone, sp.order = name, role, whatsapp, phone, i
                if photo:
                    if sp.photo:
                        sp.photo.delete(save=False)
                    sp.photo = photo
                sp.save()
            else:
                TenantSalesPerson.objects.create(
                    tenant=tenant, name=name, role=role, whatsapp=whatsapp,
                    phone=phone, order=i, photo=photo if photo else None,
                )

        # Update order + title + description + link of existing hero images
        hero_orders = request.POST.getlist('hero_image_order[]')
        hero_ids = request.POST.getlist('hero_image_id[]')
        hero_links = request.POST.getlist('hero_image_link[]')
        hero_titles = request.POST.getlist('hero_image_title[]')
        hero_descs = request.POST.getlist('hero_image_desc[]')
        for i, (hero_id, order_val) in enumerate(zip(hero_ids, hero_orders)):
            link = (hero_links[i].strip() if i < len(hero_links) else '')
            title = (hero_titles[i].strip() if i < len(hero_titles) else '')
            desc = (hero_descs[i].strip() if i < len(hero_descs) else '')
            try:
                TenantHeroImage.objects.filter(id=hero_id, tenant=tenant).update(
                    order=int(order_val), link_url=link, title=title, description=desc)
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

        # "How we work" steps — rebuild from the repeatable rows (in row order).
        ws_titles = request.POST.getlist('ws_title[]')
        if ws_titles is not None:
            ws_icons = request.POST.getlist('ws_icon[]')
            ws_descs = request.POST.getlist('ws_desc[]')
            tenant.work_steps.all().delete()
            order = 0
            for i, title in enumerate(ws_titles):
                title = (title or '').strip()
                if not title:
                    continue
                TenantWorkStep.objects.create(
                    tenant=tenant,
                    icon=(ws_icons[i].strip() if i < len(ws_icons) else ''),
                    title=title,
                    description=(ws_descs[i].strip() if i < len(ws_descs) else ''),
                    order=order,
                    is_active=True,
                )
                order += 1

        messages.success(request, 'تم حفظ الإعدادات بنجاح!')
        # Bust tenant branding cache so new rates take effect immediately
        from django.core.cache import cache as _cache
        _schema = getattr(connection, 'schema_name', 'public')
        _cache.delete(f"tenant_branding:{_schema}")
        # Homepage chrome/sections (ticker, "how we work", etc.) are baked into
        # the cached home HTML/context — bust those too so edits show at once.
        # Keys carry a catalog-filter signature suffix → clear all variants.
        try:
            if hasattr(_cache, 'delete_pattern'):
                _cache.delete_pattern(f"home_html_v9:{_schema}*")
                _cache.delete_pattern(f"home_ctx_v9:{_schema}*")
                _cache.delete_pattern(f"landing_html:{_schema}*")
            else:
                _cache.delete(f"home_html_v9:{_schema}")
                _cache.delete(f"home_ctx_v9:{_schema}")
        except Exception:
            pass
        return redirect('site_settings')
    
    # Catalog-filter options: manufacturers (shared) + the current selections so
    # the admin can pick what shows on their site.
    _cf = tenant.catalog_filter or {}
    try:
        from cars.models import Manufacturer
        _catalog_makes = list(Manufacturer.objects.order_by('name').values('id', 'name', 'name_ar'))
    except Exception:
        _catalog_makes = []
    _panel_labels = [
        ('hood_front', 'غطاء المحرك'), ('roof', 'السقف'), ('trunk_lid', 'غطاء الصندوق'),
        ('left_front_fender', 'رفرف أمامي أيسر'), ('right_front_fender', 'رفرف أمامي أيمن'),
        ('left_front_door', 'باب أمامي أيسر'), ('right_front_door', 'باب أمامي أيمن'),
        ('left_rear_door', 'باب خلفي أيسر'), ('right_rear_door', 'باب خلفي أيمن'),
        ('left_rear_quarter', 'جانب خلفي أيسر'), ('right_rear_quarter', 'جانب خلفي أيمن'),
        ('front_member', 'شاصي أمامي'), ('rear_member', 'شاصي خلفي'),
        ('center_floor', 'أرضية وسطية'), ('rear_floor', 'أرضية خلفية'),
    ]
    # A config saved before the auction/encar split is flat (no auction/encar
    # keys) and applied to both — show it in both sections so it stays visible.
    _is_split = ('auction' in _cf) or ('encar' in _cf)

    def _sel(prefix, label, show_panels):
        r = (_cf.get(prefix) or {}) if _is_split else _cf
        return {
            'prefix': prefix, 'label': label, 'show_panels': show_panels,
            'makes': r.get('makes') or [], 'models': r.get('models') or [],
            'types': r.get('exclude_types') or [], 'panels': r.get('exclude_panels') or [],
            'year_min': r.get('year_min') or '', 'year_max': r.get('year_max') or '',
            'price_min': r.get('price_min') or '', 'price_max': r.get('price_max') or '',
        }
    catalog_sections = [
        _sel('auction', 'المزادات', True),
        _sel('encar', 'Encar (السيارات العادية)', False),
    ]
    context = {
        'tenant': tenant,
        'phone_numbers': tenant.phone_numbers.all(),
        'phone_types': TenantPhoneNumber.PHONE_TYPES,
        'sales_people_admin': tenant.sales_people.all().order_by('order', 'id'),
        'hero_images': tenant.hero_images.all(),
        'work_steps_admin': tenant.work_steps.all().order_by('order', 'id'),
        'site_font_choices': font_choices(),
        'page_links': friendly_page_links(),
        'catalog_makes': _catalog_makes,
        'catalog_panel_labels': _panel_labels,
        'catalog_sections': catalog_sections,
        'theme_options': [
            ('default', 'الافتراضي', 'تصميم قياسي نظيف'),
            ('glassy', 'زجاجي', 'داكن متوهّج وعصري'),
            ('modern', 'عصري', 'كوري حديث وأنيق'),
        ],
        'landing_design_choices': tenant.LANDING_DESIGN_CHOICES,
    }
    return render(request, 'tenants/site_settings.html', context)
