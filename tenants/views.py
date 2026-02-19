from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db import connection
from .models import Tenant, TenantPhoneNumber, TenantHeroImage


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
        
        # Update colors
        tenant.primary_color = request.POST.get('primary_color', tenant.primary_color)
        tenant.secondary_color = request.POST.get('secondary_color', tenant.secondary_color)
        tenant.accent_color = request.POST.get('accent_color', tenant.accent_color)
        
        # Update footer
        tenant.footer_text = request.POST.get('footer_text', tenant.footer_text)
        tenant.footer_text_en = request.POST.get('footer_text_en', tenant.footer_text_en)
        
        # Update business info
        tenant.about = request.POST.get('about', tenant.about)
        tenant.about_en = request.POST.get('about_en', tenant.about_en)
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
        return redirect('site_settings')
    
    context = {
        'tenant': tenant,
        'phone_numbers': tenant.phone_numbers.all(),
        'phone_types': TenantPhoneNumber.PHONE_TYPES,
        'hero_images': tenant.hero_images.all(),
    }
    return render(request, 'tenants/site_settings.html', context)
