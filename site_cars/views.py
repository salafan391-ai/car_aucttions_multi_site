from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.db import connection
from django.db.models import Avg, Sum, Count, Q
from django.http import Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone

from cars.models import ApiCar, Manufacturer, CarModel
from .models import SiteCar, SiteCarImage, SiteOrder, SiteBill, SiteRating, SiteQuestion, SiteSoldCar, SiteMessage, SiteEmailLog
from .image_utils import optimize_image, batch_optimize_images


def _is_public_schema():
    return connection.schema_name == 'public'


@staff_member_required
def dashboard(request):
    if _is_public_schema():
        return redirect('home')
    now = timezone.now()
    thirty_days_ago = now - timezone.timedelta(days=30)

    # Stats
    total_site_cars = SiteCar.objects.count()
    available_site_cars = SiteCar.objects.filter(status='available').count()
    total_orders = SiteOrder.objects.count()
    pending_orders = SiteOrder.objects.filter(status='pending').count()
    completed_orders = SiteOrder.objects.filter(status='completed').count()
    total_sold = SiteSoldCar.objects.count()
    total_ratings = SiteRating.objects.count()
    pending_ratings = SiteRating.objects.filter(is_approved=False).count()
    avg_rating = SiteRating.objects.filter(is_approved=True).aggregate(avg=Avg('rating'))['avg'] or 0
    unanswered_questions = SiteQuestion.objects.filter(is_answered=False).count()
    total_revenue = SiteSoldCar.objects.aggregate(total=Sum('sale_price'))['total'] or 0
    monthly_orders = SiteOrder.objects.filter(created_at__gte=thirty_days_ago).count()
    monthly_sold = SiteSoldCar.objects.filter(sold_at__gte=thirty_days_ago).count()

    # Recent data
    recent_orders = SiteOrder.objects.select_related('car', 'user').all()[:10]
    recent_ratings = SiteRating.objects.select_related('car', 'user').filter(is_approved=False)[:5]
    recent_questions = SiteQuestion.objects.select_related('car', 'user').filter(is_answered=False)[:5]
    recent_sold = SiteSoldCar.objects.select_related('car', 'buyer').all()[:5]
    site_cars_list = SiteCar.objects.all()[:10]

    context = {
        'total_site_cars': total_site_cars,
        'available_site_cars': available_site_cars,
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'completed_orders': completed_orders,
        'total_sold': total_sold,
        'total_ratings': total_ratings,
        'pending_ratings': pending_ratings,
        'avg_rating': round(avg_rating, 1),
        'unanswered_questions': unanswered_questions,
        'total_revenue': total_revenue,
        'monthly_orders': monthly_orders,
        'monthly_sold': monthly_sold,
        'recent_orders': recent_orders,
        'recent_ratings': recent_ratings,
        'recent_questions': recent_questions,
        'recent_sold': recent_sold,
        'site_cars_list': site_cars_list,
    }
    return render(request, 'site_cars/dashboard.html', context)


def site_car_list(request):
    if _is_public_schema():
        return redirect('home')
    
    # By default, exclude sold cars
    status = request.GET.get('status', 'active')
    if status == 'sold':
        qs = SiteCar.objects.filter(status='sold')
    elif status == 'all':
        qs = SiteCar.objects.all()
    else:
        qs = SiteCar.objects.exclude(status='sold')

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(title__icontains=q)

    sort = request.GET.get('sort', '-created_at')
    allowed_sorts = ['-created_at', 'price', '-price', '-year', 'mileage']
    if sort in allowed_sorts:
        qs = qs.order_by(sort)

    sold_count = SiteCar.objects.filter(status='sold').count()
    active_count = SiteCar.objects.exclude(status='sold').count()

    context = {
        'site_cars': qs,
        'sold_count': sold_count,
        'active_count': active_count,
        'current_status': status,
    }
    return render(request, 'site_cars/site_car_list.html', context)


@staff_member_required
def site_car_add(request):
    """Add a new site car"""
    if _is_public_schema():
        return redirect('home')
    
    if request.method == 'POST':
        car = SiteCar.objects.create(
            title=request.POST.get('title', ''),
            description=request.POST.get('description', ''),
            manufacturer=request.POST.get('manufacturer', ''),
            model=request.POST.get('model', ''),
            year=int(request.POST.get('year', 2024)),
            color=request.POST.get('color', ''),
            mileage=int(request.POST.get('mileage', 0) or 0),
            price=int(request.POST.get('price', 0) or 0),
            transmission=request.POST.get('transmission', ''),
            fuel=request.POST.get('fuel', ''),
            body_type=request.POST.get('body_type', ''),
            engine=request.POST.get('engine', ''),
            drive_wheel=request.POST.get('drive_wheel', ''),
            status=request.POST.get('status', 'available'),
            is_featured=request.POST.get('is_featured') == 'on',
        )
        
        # Handle main image with optimization
        if 'image' in request.FILES:
            car.image = optimize_image(request.FILES['image'])
            car.save()
        
        # Handle gallery images with batch optimization
        gallery_images = request.FILES.getlist('gallery')
        if gallery_images:
            # Optimize images in batches to prevent memory issues
            optimized_images = batch_optimize_images(gallery_images, max_workers=2)
            for idx, img in enumerate(optimized_images):
                SiteCarImage.objects.create(car=car, image=img, order=idx)
        
        messages.success(request, 'تم إضافة السيارة بنجاح')
        return redirect('site_car_list')
    
    manufacturers = Manufacturer.objects.all().order_by('name')
    models = CarModel.objects.all().order_by('name')
    return render(request, 'site_cars/site_car_form.html', {
        'action': 'add',
        'manufacturers': manufacturers,
        'car_models': models,
    })


@staff_member_required
def site_car_edit(request, pk):
    """Edit an existing site car"""
    if _is_public_schema():
        return redirect('home')
    
    car = get_object_or_404(SiteCar, pk=pk)
    
    if request.method == 'POST':
        car.title = request.POST.get('title', car.title)
        car.description = request.POST.get('description', car.description)
        car.manufacturer = request.POST.get('manufacturer', car.manufacturer)
        car.model = request.POST.get('model', car.model)
        car.year = int(request.POST.get('year', car.year))
        car.color = request.POST.get('color', car.color)
        car.mileage = int(request.POST.get('mileage', car.mileage) or 0)
        car.price = int(request.POST.get('price', car.price) or 0)
        car.transmission = request.POST.get('transmission', car.transmission)
        car.fuel = request.POST.get('fuel', car.fuel)
        car.body_type = request.POST.get('body_type', car.body_type)
        car.engine = request.POST.get('engine', car.engine)
        car.drive_wheel = request.POST.get('drive_wheel', car.drive_wheel)
        car.status = request.POST.get('status', car.status)
        car.is_featured = request.POST.get('is_featured') == 'on'
        
        # Handle main image with optimization
        if 'image' in request.FILES:
            car.image = optimize_image(request.FILES['image'])
        
        car.save()
        
        # Handle gallery images with batch optimization
        gallery_images = request.FILES.getlist('gallery')
        if gallery_images:
            last_order = car.gallery.count()
            # Optimize images in batches to prevent memory issues
            optimized_images = batch_optimize_images(gallery_images, max_workers=2)
            for idx, img in enumerate(optimized_images):
                SiteCarImage.objects.create(car=car, image=img, order=last_order + idx)
        
        messages.success(request, 'تم تحديث السيارة بنجاح')
        return redirect('site_car_list')
    
    manufacturers = Manufacturer.objects.all().order_by('name')
    models = CarModel.objects.all().order_by('name')
    return render(request, 'site_cars/site_car_form.html', {
        'action': 'edit',
        'car': car,
        'manufacturers': manufacturers,
        'car_models': models,
    })


@staff_member_required
def site_car_delete(request, pk):
    """Delete a site car"""
    if _is_public_schema():
        return redirect('home')
    
    car = get_object_or_404(SiteCar, pk=pk)
    
    # Prevent deletion of sold cars
    if car.status == 'sold':
        messages.error(request, 'لا يمكن حذف السيارات المباعة. يرجى الانتقال إلى صفحة السيارات المباعة.')
        return redirect('sold_cars')
    
    if request.method == 'POST':
        car.delete()
        messages.success(request, 'تم حذف السيارة بنجاح')
        return redirect('site_car_list')
    
    return render(request, 'site_cars/site_car_delete.html', {'car': car})


@staff_member_required
def site_car_change_status(request, pk):
    """Change the status of a site car"""
    if _is_public_schema():
        return redirect('home')
    
    car = get_object_or_404(SiteCar, pk=pk)
    
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in dict(SiteCar.STATUS_CHOICES):
            car.status = new_status
            car.save()
            messages.success(request, f'تم تغيير حالة السيارة إلى {car.get_status_display()}')
    
    return redirect(request.META.get('HTTP_REFERER', 'site_car_list'))


@staff_member_required
def site_car_delete_image(request, pk, image_id):
    """Delete a gallery image from a site car"""
    if _is_public_schema():
        return redirect('home')
    
    image = get_object_or_404(SiteCarImage, pk=image_id, car_id=pk)
    image.delete()
    messages.success(request, 'تم حذف الصورة بنجاح')
    return redirect('site_car_edit', pk=pk)


def site_car_detail(request, pk):
    if _is_public_schema():
        return redirect('home')
    car = get_object_or_404(SiteCar, pk=pk)
    return render(request, 'site_cars/site_car_detail.html', {'car': car})


def sold_cars(request):
    if _is_public_schema():
        return redirect('home')
    sold = SiteSoldCar.objects.select_related('car__manufacturer', 'car__model', 'car__color', 'buyer').all()
    return render(request, 'site_cars/sold_cars.html', {'sold_cars': sold})


@login_required
@login_required
def place_order(request, pk):
    if _is_public_schema():
        return redirect('home')
    car = get_object_or_404(ApiCar, pk=pk)

    if request.method == 'POST':
        offer_price = request.POST.get('offer_price', '').strip()
        notes = request.POST.get('notes', '').strip()

        if not offer_price:
            messages.error(request, 'يرجى إدخال السعر المعروض.')
            return render(request, 'site_cars/place_order.html', {'car': car})

        try:
            offer_price = float(offer_price)
        except ValueError:
            messages.error(request, 'السعر المعروض غير صالح.')
            return render(request, 'site_cars/place_order.html', {'car': car})

        order = SiteOrder.objects.create(
            user=request.user,
            car=car,
            offer_price=offer_price,
            notes=notes,
        )
        from .email_utils import send_order_placed_email
        send_order_placed_email(order)
        messages.success(request, 'تم إرسال طلبك بنجاح! سنتواصل معك قريباً.')
        return redirect('my_orders')

    return render(request, 'site_cars/place_order.html', {'car': car})


@login_required
def my_orders(request):
    if _is_public_schema():
        return redirect('home')
    orders = SiteOrder.objects.filter(user=request.user).select_related('car')
    return render(request, 'site_cars/my_orders.html', {'orders': orders})


@login_required
def order_detail(request, pk):
    if _is_public_schema():
        return redirect('home')
    order = get_object_or_404(
        SiteOrder.objects.select_related('car'),
        pk=pk,
        user=request.user,
    )
    return render(request, 'site_cars/order_detail.html', {'order': order})


@login_required
def rate_car(request, pk):
    if _is_public_schema():
        return redirect('home')
    car = get_object_or_404(ApiCar, pk=pk)

    if request.method == 'POST':
        rating_val = request.POST.get('rating', '').strip()
        comment = request.POST.get('comment', '').strip()

        if not rating_val or int(rating_val) not in range(1, 6):
            messages.error(request, 'يرجى اختيار تقييم من 1 إلى 5.')
            return redirect('car_detail', pk=pk)

        SiteRating.objects.update_or_create(
            user=request.user,
            car=car,
            defaults={
                'rating': int(rating_val),
                'comment': comment,
                'is_approved': False,  # Ratings need admin approval
            },
        )
        messages.success(request, 'تم حفظ تقييمك بنجاح! سيتم عرضه بعد مراجعة المشرف.')

    return redirect('car_detail', pk=pk)


@staff_member_required
def approve_rating(request, pk):
    """Approve a rating"""
    if _is_public_schema():
        return redirect('home')
    
    rating = get_object_or_404(SiteRating, pk=pk)
    rating.is_approved = True
    rating.save()
    messages.success(request, f'تم الموافقة على تقييم {rating.user.username}')
    
    # Redirect back to the car detail page or referrer
    return redirect(request.META.get('HTTP_REFERER', 'car_detail'), pk=rating.car.id)


@staff_member_required
def reject_rating(request, pk):
    """Reject and delete a rating"""
    if _is_public_schema():
        return redirect('home')
    
    rating = get_object_or_404(SiteRating, pk=pk)
    car_id = rating.car.id
    username = rating.user.username
    rating.delete()
    messages.success(request, f'تم رفض وحذف تقييم {username}')
    
    # Redirect back to the car detail page or referrer
    return redirect(request.META.get('HTTP_REFERER', 'car_detail'), pk=car_id)


# ── Inbox / Messaging ──

@login_required
def inbox(request):
    if _is_public_schema():
        return redirect('home')
    received = SiteMessage.objects.filter(recipient=request.user).select_related('sender')
    sent = SiteMessage.objects.filter(sender=request.user).select_related('recipient')
    unread_count = received.filter(is_read=False).count()
    tab = request.GET.get('tab', 'received')
    context = {
        'received': received,
        'sent': sent,
        'unread_count': unread_count,
        'tab': tab,
    }
    return render(request, 'site_cars/inbox.html', context)


@login_required
def message_detail(request, pk):
    if _is_public_schema():
        return redirect('home')
    msg = get_object_or_404(SiteMessage, pk=pk)
    if msg.recipient != request.user and msg.sender != request.user:
        return redirect('inbox')
    if msg.recipient == request.user and not msg.is_read:
        msg.is_read = True
        msg.save(update_fields=['is_read'])
    replies = msg.replies.all().select_related('sender', 'recipient')
    if request.method == 'POST':
        body = request.POST.get('body', '').strip()
        if body:
            reply_to = msg.sender if msg.recipient == request.user else msg.recipient
            SiteMessage.objects.create(
                sender=request.user,
                recipient=reply_to,
                subject=f"رد: {msg.subject}",
                body=body,
                parent=msg,
            )
            messages.success(request, 'تم إرسال الرد.')
            return redirect('message_detail', pk=pk)
    return render(request, 'site_cars/message_detail.html', {'msg': msg, 'replies': replies})


@login_required
def compose_message(request):
    if _is_public_schema():
        return redirect('home')
    from django.contrib.auth.models import User as AuthUser
    if request.method == 'POST':
        recipient_id = request.POST.get('recipient')
        subject = request.POST.get('subject', '').strip()
        body = request.POST.get('body', '').strip()
        if recipient_id and subject and body:
            recipient = get_object_or_404(AuthUser, pk=recipient_id)
            SiteMessage.objects.create(
                sender=request.user,
                recipient=recipient,
                subject=subject,
                body=body,
            )
            messages.success(request, 'تم إرسال الرسالة.')
            return redirect('inbox')
        else:
            messages.error(request, 'يرجى ملء جميع الحقول.')

    if request.user.is_staff:
        users = AuthUser.objects.exclude(pk=request.user.pk).order_by('username')
    else:
        users = AuthUser.objects.filter(is_staff=True).exclude(pk=request.user.pk)
    return render(request, 'site_cars/compose_message.html', {'users': users})


# ── Admin: Send Email / Broadcast ──

@staff_member_required
def send_email_view(request):
    if _is_public_schema():
        return redirect('home')
    from django.contrib.auth.models import User as AuthUser
    from .email_utils import send_tenant_email, send_broadcast_email

    if request.method == 'POST':
        send_type = request.POST.get('send_type', 'single')
        subject = request.POST.get('subject', '').strip()
        body = request.POST.get('body', '').strip()

        if not subject or not body:
            messages.error(request, 'يرجى ملء الموضوع والمحتوى.')
        elif send_type == 'broadcast':
            count = send_broadcast_email(subject, body)
            messages.success(request, f'تم إرسال البريد إلى {count} مستخدم.')
            return redirect('site_dashboard')
        else:
            recipient_email = request.POST.get('recipient_email', '').strip()
            if not recipient_email:
                messages.error(request, 'يرجى إدخال البريد الإلكتروني.')
            else:
                user = AuthUser.objects.filter(email=recipient_email).first()
                success = send_tenant_email(recipient_email, subject, body, 'custom', user)
                if success:
                    messages.success(request, f'تم إرسال البريد إلى {recipient_email}.')
                else:
                    messages.error(request, 'فشل إرسال البريد. تحقق من إعدادات SMTP.')
                return redirect('send_email')

    recent_logs = SiteEmailLog.objects.all()[:20]
    return render(request, 'site_cars/send_email.html', {'recent_logs': recent_logs})


# ── Admin: Upload Auction JSON ──

@staff_member_required
def upload_auction_json(request):
    if _is_public_schema():
        return redirect('home')
    import json
    from datetime import datetime
    from django.core.exceptions import MultipleObjectsReturned
    from django.db import transaction
    from cars.models import Manufacturer, CarModel, CarBadge, CarColor, BodyType, Category

    def safe_get_or_create(manager, defaults=None, **kwargs):
        try:
            obj, _ = manager.get_or_create(defaults=defaults or {}, **kwargs)
            return obj
        except MultipleObjectsReturned:
            return manager.filter(**kwargs).order_by("id").first()

    def parse_mileage(val):
        """Parse mileage value, removing commas and 'km' suffix"""
        if not val:
            return 0
        if isinstance(val, (int, float)):
            return int(val)
        # Remove commas, 'km', and any whitespace, then convert to int
        cleaned = str(val).replace(",", "").replace("km", "").replace("KM", "").replace("Km", "").strip()
        try:
            return int(cleaned) if cleaned else 0
        except ValueError:
            return 0

    def parse_power(val):
        """Parse power value, removing commas and 'cc' suffix"""
        if not val:
            return 0
        if isinstance(val, (int, float)):
            return int(val)
        # Remove commas, 'cc', and any whitespace, then convert to int
        cleaned = str(val).replace(",", "").replace("cc", "").replace("CC", "").strip()
        try:
            return int(cleaned) if cleaned else 0
        except ValueError:
            return 0

    def parse_auction_date(val):
        if not val:
            return None
        from zoneinfo import ZoneInfo
        from django.utils.timezone import make_aware
        sa_tz = ZoneInfo("Asia/Riyadh")
        for fmt in ("%d/%m/%Y %I:%M %p", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                naive_dt = datetime.strptime(val.strip(), fmt)
                return make_aware(naive_dt, sa_tz)
            except ValueError:
                continue
        return None

    if request.method == 'POST' and request.FILES.get('json_file'):
        json_file = request.FILES['json_file']
        try:
            data = json.load(json_file)
        except json.JSONDecodeError:
            messages.error(request, 'ملف JSON غير صالح.')
            return redirect('upload_auction_json')

        if not isinstance(data, list):
            messages.error(request, 'يجب أن يكون الملف قائمة من السيارات.')
            return redirect('upload_auction_json')

        # Pre-fetch all related objects to minimize database queries
        auction_category = safe_get_or_create(Category.objects, name="auction")
        
        # Get all existing car IDs in one query
        existing_car_ids = set(
            ApiCar.objects.filter(
                car_id__in=[
                    (item.get("car_identifire") or item.get("car_ids") or "").strip() 
                    for item in data
                ]
            ).values_list('car_id', flat=True)
        )
        
        # Pre-load all manufacturers, models, badges, colors, and body types
        all_manufacturers = {m.name: m for m in Manufacturer.objects.all()}
        all_models = {(m.name, m.manufacturer_id): m for m in CarModel.objects.select_related('manufacturer').all()}
        all_colors = {c.name: c for c in CarColor.objects.all()}
        all_badges = {(b.name, b.model_id): b for b in CarBadge.objects.select_related('model').all()}
        
        # Collect new objects to create
        new_manufacturers = {}
        new_models = {}
        new_colors = {}
        
        cars_to_create = []
        cars_to_update = []
        created = updated = skipped = 0

        for item in data:
            car_id = (item.get("car_identifire") or item.get("car_ids") or "").strip()
            if not car_id:
                skipped += 1
                continue

            # Handle manufacturer
            make_name = item.get("make_en") or item.get("make") or "Unknown"
            if make_name not in all_manufacturers and make_name not in new_manufacturers:
                new_manufacturers[make_name] = Manufacturer(name=make_name, country="Unknown")
            manufacturer = all_manufacturers.get(make_name) or new_manufacturers.get(make_name)

            # Handle model
            model_name = item.get("models_en") or item.get("models") or "Unknown"
            model_key = (model_name, manufacturer.id if hasattr(manufacturer, 'id') else None)
            # Store manufacturer name (string) for new models so we can resolve
            # to the saved Manufacturer instance after bulk-creating missing manufacturers.
            if model_key not in all_models and model_name not in new_models:
                new_models[model_name] = (model_name, make_name)
            
            # Handle color
            color_name = item.get("color_en") or item.get("color") or "Unknown"
            if color_name not in all_colors and color_name not in new_colors:
                new_colors[color_name] = CarColor(name=color_name)
            
            # Handle body type
            

        # Bulk create missing manufacturers
        if new_manufacturers:
            Manufacturer.objects.bulk_create(new_manufacturers.values(), ignore_conflicts=True)
            all_manufacturers.update({m.name: m for m in Manufacturer.objects.filter(name__in=new_manufacturers.keys())})
        
        # Bulk create missing colors
        if new_colors:
            CarColor.objects.bulk_create(new_colors.values(), ignore_conflicts=True)
            all_colors.update({c.name: c for c in CarColor.objects.filter(name__in=new_colors.keys())})
        
       
        # Bulk create missing models
        if new_models:
            models_to_create = []
            for model_name, make_name in new_models.values():
                manufacturer_obj = all_manufacturers.get(make_name)
                if manufacturer_obj:
                    models_to_create.append(CarModel(name=model_name, manufacturer=manufacturer_obj))
            if models_to_create:
                CarModel.objects.bulk_create(models_to_create, ignore_conflicts=True)
            all_models.update({
                (m.name, m.manufacturer_id): m 
                for m in CarModel.objects.filter(name__in=[name for name, _ in new_models.values()]).select_related('manufacturer')
            })
        
        
        
        # Now process all cars
        for item in data:
            car_id = (item.get("car_identifire") or item.get("car_ids") or "").strip()
            if not car_id:
                continue

            make_name = item.get("make_en") or item.get("make") or "Unknown"
            manufacturer = all_manufacturers.get(make_name)
            
            model_name = item.get("models_en") or item.get("models") or "Unknown"
            model_key = (model_name, manufacturer.id if manufacturer else None)
            car_model = all_models.get(model_key)
            # If model is missing but we have a manufacturer, create or reuse an
            # 'Unknown' model for this manufacturer to allow creating a badge.
            if not car_model and manufacturer:
                unknown_model_key = ("Unknown", manufacturer.id)
                car_model = all_models.get(unknown_model_key)
                if not car_model:
                    car_model = CarModel.objects.create(name='Unknown', manufacturer=manufacturer)
                    all_models[(car_model.name, car_model.manufacturer_id)] = car_model
            
     
            
            # Resolve badge. Auctions feeds often omit badge info; in that case
            # prefer an existing badge for the model. Only create a placeholder
            # badge when no badge exists for the model to avoid creating many
            # meaningless badges.
            raw_badge = (item.get("badge_en") or item.get("badge") or item.get("trim"))
            badge = None
            if raw_badge and raw_badge.strip():
                badge_name = raw_badge.strip()
                badge_key = (badge_name, car_model.id if car_model else None)
                badge = all_badges.get(badge_key)
                if not badge and car_model:
                    badge = CarBadge.objects.filter(model=car_model, name__iexact=badge_name).first()
                    if not badge:
                        badge = CarBadge.objects.create(name=badge_name, model=car_model)
                    all_badges[(badge.name, badge.model_id)] = badge
            else:
                # No badge provided in feed — reuse first existing badge for model
                if car_model:
                    badge = CarBadge.objects.filter(model=car_model).first()
                    if badge:
                        all_badges[(badge.name, badge.model_id)] = badge
                    else:
                        # create a single placeholder badge for this model
                        badge = CarBadge.objects.create(name='Unknown', model=car_model)
                        all_badges[(badge.name, badge.model_id)] = badge

            color_name = item.get("color_en") or item.get("color") or "Unknown"
            color = all_colors.get(color_name)
            
   

            title = item.get("title") or f"{make_name} {model_name}"
            
            
            car_data = {
                "car_id": car_id,
                "title": title[:100],
                "image": (item.get("image") or "")[:255],
                "manufacturer": manufacturer,
                "category": auction_category,
                "auction_date": parse_auction_date(item.get("auction_date")),
                "auction_name": (item.get("auction_name") or "")[:100],
                "lot_number": car_id,
                "model": car_model,
                "badge": badge,
                "year": int(item.get("year") or 0),
                "color": color,
                "transmission": (item.get("mission") or "")[:100],
                "power": parse_power(item.get("power")),
                "price": int(item.get("price") or 0),
                "mileage": parse_mileage(item.get("mileage")),
                "fuel": (item.get("fuel_en") or item.get("fuel") or "")[:100],
                "images": item.get("images") or [],
                "inspection_image": item.get("inspection_image") or "",
                "points": str(item.get("points") or item.get("score") or "")[:50],
                "address": (item.get("region") or "")[:255],
                "seat_count": int(item.get("seats") or 0),
                "entry": item.get("entry") or "",
                "vin": car_id,
            }
            
            # If we don't have a resolved badge, skip the row to avoid DB constraint errors
            if not badge:
                skipped += 1
                continue

            if car_id in existing_car_ids:
                cars_to_update.append(car_data)
            else:
                cars_to_create.append(ApiCar(**car_data))

        # Bulk create new cars
        with transaction.atomic():
            if cars_to_create:
                ApiCar.objects.bulk_create(cars_to_create, batch_size=500)
                created = len(cars_to_create)
            
            # Bulk update existing cars
            if cars_to_update:
                existing_cars = {car.car_id: car for car in ApiCar.objects.filter(car_id__in=[c['car_id'] for c in cars_to_update])}
                cars_to_bulk_update = []
                
                for car_data in cars_to_update:
                    car_id = car_data.pop('car_id')
                    if car_id in existing_cars:
                        car = existing_cars[car_id]
                        for key, value in car_data.items():
                            setattr(car, key, value)
                        cars_to_bulk_update.append(car)
                
                if cars_to_bulk_update:
                    ApiCar.objects.bulk_update(
                        cars_to_bulk_update,
                        ['title', 'image', 'manufacturer', 'category', 'auction_date', 'auction_name', 
                         'lot_number', 'model', 'year', 'color', 'transmission', 'power', 
                         'price', 'mileage', 'fuel', 'images', 'inspection_image', 'points', 
                         'address', 'vin',"seat_count", "entry"],
                        batch_size=500
                    )
                    updated = len(cars_to_bulk_update)

            # Always fix any missing slugs (covers both new and pre-existing cars)
            from django.db import connection as _conn
            with _conn.cursor() as cur:
                cur.execute("""
                    UPDATE cars_apicar
                    SET slug = CONCAT(
                        COALESCE(CAST(year AS TEXT), ''), '-',
                        LOWER(REGEXP_REPLACE(
                            COALESCE((SELECT name FROM cars_manufacturer WHERE id = manufacturer_id), ''),
                            '[^a-zA-Z0-9]+', '-', 'g'
                        )), '-',
                        LOWER(REGEXP_REPLACE(
                            COALESCE((SELECT name FROM cars_carmodel WHERE id = model_id), ''),
                            '[^a-zA-Z0-9]+', '-', 'g'
                        )), '-',
                        CAST(id AS TEXT)
                    )
                    WHERE slug IS NULL OR slug = ''
                """)

        messages.success(request, f'تم الاستيراد بنجاح! {created} سيارة جديدة، {updated} سيارة محدّثة، {skipped} تم تخطيها')
        return redirect('upload_auction_json')

    # GET — show recent auction cars
    recent_auctions = ApiCar.objects.filter(category__name='auction').order_by('-created_at')[:20]
    return render(request, 'site_cars/upload_auction_json.html', {'recent_auctions': recent_auctions})
