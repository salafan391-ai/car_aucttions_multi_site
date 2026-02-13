from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Avg, Sum, Count, Q
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone

from cars.models import ApiCar
from .models import SiteCar, SiteCarImage, SiteOrder, SiteBill, SiteRating, SiteQuestion, SiteSoldCar, SiteMessage, SiteEmailLog


@staff_member_required
def dashboard(request):
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
    avg_rating = SiteRating.objects.aggregate(avg=Avg('rating'))['avg'] or 0
    unanswered_questions = SiteQuestion.objects.filter(is_answered=False).count()
    total_revenue = SiteSoldCar.objects.aggregate(total=Sum('sale_price'))['total'] or 0
    monthly_orders = SiteOrder.objects.filter(created_at__gte=thirty_days_ago).count()
    monthly_sold = SiteSoldCar.objects.filter(sold_at__gte=thirty_days_ago).count()

    # Recent data
    recent_orders = SiteOrder.objects.select_related('car', 'user').all()[:10]
    recent_ratings = SiteRating.objects.select_related('car', 'user').all()[:5]
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
    qs = SiteCar.objects.all()

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(title__icontains=q)

    sort = request.GET.get('sort', '-created_at')
    allowed_sorts = ['-created_at', 'price', '-price', '-year', 'mileage']
    if sort in allowed_sorts:
        qs = qs.order_by(sort)

    context = {'site_cars': qs}
    return render(request, 'site_cars/site_car_list.html', context)


def site_car_detail(request, pk):
    car = get_object_or_404(SiteCar, pk=pk)
    return render(request, 'site_cars/site_car_detail.html', {'car': car})


def sold_cars(request):
    sold = SiteSoldCar.objects.select_related('car__manufacturer', 'car__model', 'car__color', 'buyer').all()
    return render(request, 'site_cars/sold_cars.html', {'sold_cars': sold})


@login_required
def place_order(request, pk):
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
    orders = SiteOrder.objects.filter(user=request.user).select_related('car')
    return render(request, 'site_cars/my_orders.html', {'orders': orders})


@login_required
def order_detail(request, pk):
    order = get_object_or_404(
        SiteOrder.objects.select_related('car'),
        pk=pk,
        user=request.user,
    )
    return render(request, 'site_cars/order_detail.html', {'order': order})


@login_required
def rate_car(request, pk):
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
            },
        )
        messages.success(request, 'تم حفظ تقييمك بنجاح!')

    return redirect('car_detail', pk=pk)


# ── Inbox / Messaging ──

@login_required
def inbox(request):
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
        if not val:
            return 0
        if isinstance(val, (int, float)):
            return int(val)
        return int(val.replace(",", "").strip() or 0)

    def parse_auction_date(val):
        if not val:
            return None
        for fmt in ("%d/%m/%Y %I:%M %p", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(val.strip(), fmt).date()
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

        auction_category = safe_get_or_create(Category.objects, name="auction")
        manu_cache, model_cache, badge_cache, color_cache, body_cache = {}, {}, {}, {}, {}
        created = updated = skipped = 0

        for item in data:
            car_id = (item.get("car_identifire") or item.get("car_ids") or "").strip()
            if not car_id:
                skipped += 1
                continue

            make_name = item.get("make_en") or item.get("make") or "Unknown"
            if make_name not in manu_cache:
                manu_cache[make_name] = safe_get_or_create(Manufacturer.objects, defaults={"country": "Unknown"}, name=make_name)
            manufacturer = manu_cache[make_name]

            model_name = item.get("models_en") or item.get("models") or "Unknown"
            model_key = (model_name, manufacturer.id)
            if model_key not in model_cache:
                model_cache[model_key] = safe_get_or_create(CarModel.objects, name=model_name, manufacturer=manufacturer)
            car_model = model_cache[model_key]

            badge_key = (model_name, car_model.id)
            if badge_key not in badge_cache:
                badge_cache[badge_key] = safe_get_or_create(CarBadge.objects, name=model_name, model=car_model)
            badge = badge_cache[badge_key]

            color_name = item.get("color_en") or item.get("color") or "Unknown"
            if color_name not in color_cache:
                color_cache[color_name] = safe_get_or_create(CarColor.objects, name=color_name)
            color = color_cache[color_name]

            shape = (item.get("shape") or "").strip()
            body_obj = None
            if shape:
                if shape not in body_cache:
                    body_cache[shape] = safe_get_or_create(BodyType.objects, name=shape)
                body_obj = body_cache[shape]

            title = item.get("title") or f"{make_name} {model_name}"
            defaults = {
                "title": title[:100],
                "image": (item.get("image") or "")[:255],
                "manufacturer": manufacturer,
                "category": auction_category,
                "auction_date": parse_auction_date(item.get("auction_date")),
                "auction_name": (item.get("auction_name") or "")[:100],
                "lot_number": car_id,
                "model": car_model,
                "year": int(item.get("year") or 0),
                "badge": badge,
                "color": color,
                "transmission": (item.get("mission") or "")[:100],
                "power": int(item.get("power") or 0),
                "price": int(item.get("price") or 0),
                "mileage": parse_mileage(item.get("mileage")),
                "fuel": (item.get("fuel_en") or item.get("fuel") or "")[:100],
                "images": item.get("images") or [],
                "inspection_image": item.get("inspection_image") or "",
                "points": str(item.get("points") or item.get("score") or "")[:50],
                "address": (item.get("region") or "")[:255],
                "body": body_obj,
                "vin": car_id,
            }

            try:
                with transaction.atomic():
                    obj, was_created = ApiCar.objects.update_or_create(car_id=car_id, defaults=defaults)
                    if was_created:
                        created += 1
                    else:
                        updated += 1
            except Exception:
                skipped += 1

        messages.success(request, f'تم الاستيراد: {created} جديدة، {updated} محدّثة، {skipped} تم تخطيها')
        return redirect('upload_auction_json')

    # GET — show recent auction cars
    recent_auctions = ApiCar.objects.filter(category__name='auction').order_by('-created_at')[:20]
    return render(request, 'site_cars/upload_auction_json.html', {'recent_auctions': recent_auctions})
