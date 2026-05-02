import os
import subprocess
import sys
import tempfile
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Avg, Sum, Count, Q
from django.http import Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from cars.models import ApiCar, Manufacturer, CarModel
from .models import SiteCar, SiteCarImage, SiteOrder, SiteBill, SiteShipment, SiteRating, SiteQuestion, SiteSoldCar, SiteMessage, SiteEmailLog
from .image_utils import optimize_image, batch_optimize_images


def _is_public_schema():
    return connection.schema_name == 'public'


@staff_member_required
def dashboard(request):
    if _is_public_schema():
        return _saas_owner_dashboard(request)
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

    # Primary tab — "mine" (admin-uploaded) vs. "auctions" (imported cars
    # whose external_id starts with 'hc_' e.g. from HappyCar).
    source = request.GET.get('source', 'mine')  # 'mine' | 'auctions'
    external_qs = SiteCar.objects.filter(external_id__startswith='hc_')
    if source == 'auctions':
        base_qs = external_qs
    else:
        base_qs = SiteCar.objects.exclude(external_id__startswith='hc_')
        source = 'mine'

    # Secondary tab (within the selected source): active / sold / all
    status = request.GET.get('status', 'active')
    if status == 'sold':
        qs = base_qs.filter(status='sold')
    elif status == 'all':
        qs = base_qs
    else:
        qs = base_qs.exclude(status='sold')

    # ---- Filters ----
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(manufacturer__icontains=q)
            | Q(model__icontains=q) | Q(external_id__icontains=q)
        )

    def _pick(param):
        v = (request.GET.get(param) or '').strip()
        return v or None

    def _int(param):
        try:
            return int(request.GET.get(param) or '')
        except (TypeError, ValueError):
            return None

    if v := _pick('make'):
        qs = qs.filter(manufacturer__iexact=v)
    if v := _pick('fuel'):
        qs = qs.filter(fuel__iexact=v)
    if v := _pick('transmission'):
        qs = qs.filter(transmission__iexact=v)
    if (v := _int('year_min')) is not None:
        qs = qs.filter(year__gte=v)
    if (v := _int('year_max')) is not None:
        qs = qs.filter(year__lte=v)
    if (v := _int('price_min')) is not None:
        qs = qs.filter(price__gte=v)
    if (v := _int('price_max')) is not None:
        qs = qs.filter(price__lte=v)
    if (v := _int('km_max')) is not None:
        qs = qs.filter(mileage__lte=v)

    sort = request.GET.get('sort', '-created_at')
    allowed_sorts = [
        '-created_at', 'price', '-price', '-year', 'year',
        'mileage', '-mileage', 'manufacturer',
    ]
    if sort in allowed_sorts:
        qs = qs.order_by(sort)

    # ---- Counts (for the top tabs; unaffected by filters below) ----
    sold_count = base_qs.filter(status='sold').count()
    active_count = base_qs.exclude(status='sold').count()
    auctions_total = external_qs.count()
    mine_total = SiteCar.objects.exclude(external_id__startswith='hc_').count()

    # ---- Dropdown options (scoped to the active source, not the filters
    # so users can always see the full list of available values) ----
    makes = (base_qs.exclude(manufacturer__exact='')
                     .values_list('manufacturer', flat=True)
                     .distinct().order_by('manufacturer'))
    fuels = (base_qs.exclude(fuel__isnull=True).exclude(fuel__exact='')
                     .values_list('fuel', flat=True)
                     .distinct().order_by('fuel'))
    transmissions = (base_qs.exclude(transmission__isnull=True)
                            .exclude(transmission__exact='')
                            .values_list('transmission', flat=True)
                            .distinct().order_by('transmission'))

    # ---- Pagination ----
    try:
        per_page = min(max(int(request.GET.get('per_page', 24) or 24), 6), 96)
    except ValueError:
        per_page = 24
    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Build a querystring base for pager links (preserves filters, drops `page`)
    from urllib.parse import urlencode
    qs_params = {k: v for k, v in request.GET.items() if k != 'page' and v}
    qs_base = urlencode(qs_params)

    context = {
        'site_cars': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'qs_base': qs_base,
        'per_page': per_page,
        'sold_count': sold_count,
        'active_count': active_count,
        'current_status': status,
        'current_source': source,
        'auctions_total': auctions_total,
        'mine_total': mine_total,
        'is_auctions_tab': source == 'auctions',
        # filter UI state
        'filter_q': q,
        'filter_make': request.GET.get('make', ''),
        'filter_fuel': request.GET.get('fuel', ''),
        'filter_transmission': request.GET.get('transmission', ''),
        'filter_year_min': request.GET.get('year_min', ''),
        'filter_year_max': request.GET.get('year_max', ''),
        'filter_price_min': request.GET.get('price_min', ''),
        'filter_price_max': request.GET.get('price_max', ''),
        'filter_km_max': request.GET.get('km_max', ''),
        'current_sort': sort,
        'makes': list(makes),
        'fuels': list(fuels),
        'transmissions': list(transmissions),
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
        
        # Handle inspection image
        if 'inspection_image' in request.FILES:
            car.inspection_image = optimize_image(request.FILES['inspection_image'])
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
    
    manufacturers = Manufacturer.objects.only('name', 'name_ar').order_by('name')
    models = CarModel.objects.select_related('manufacturer').only('name', 'manufacturer__name').order_by('name')
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
        
        # Handle inspection image
        if 'inspection_image' in request.FILES:
            car.inspection_image = optimize_image(request.FILES['inspection_image'])
        
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
    
    manufacturers = Manufacturer.objects.only('name', 'name_ar').order_by('name')
    models = CarModel.objects.select_related('manufacturer').only('name', 'manufacturer__name').order_by('name')
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


# ── Admin: Delete Expired Auctions ──

@require_POST
@staff_member_required
def delete_expired_auctions(request):
    if not _is_public_schema():
        return redirect('home')

    from django.db import connection
    from django.utils import timezone
    from django.contrib import messages as dj_messages
    from tenants.models import Tenant

    cutoff = timezone.now()

    # Build a UNION over every tenant schema's referencing tables so we don't
    # try to delete an ApiCar that any tenant still has an order/rating/sold/
    # question pointing at.
    tenant_schemas = list(
        Tenant.objects.exclude(schema_name='public')
        .values_list('schema_name', flat=True)
    )

    if tenant_schemas:
        union_parts = []
        for schema in tenant_schemas:
            quoted = f'"{schema}"'
            union_parts.extend([
                f"SELECT car_id FROM {quoted}.site_cars_siteorder",
                f"SELECT car_id FROM {quoted}.site_cars_siterating",
                f"SELECT car_id FROM {quoted}.site_cars_sitesoldcar",
                f"SELECT car_id FROM {quoted}.site_cars_sitequestion WHERE car_id IS NOT NULL",
            ])
        referenced_sql = " UNION ALL ".join(union_parts)
        not_in_clause = f"AND a.id NOT IN ({referenced_sql})"
    else:
        not_in_clause = ""

    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT a.id FROM cars_apicar a
            INNER JOIN cars_category c ON c.id = a.category_id
            WHERE c.name = 'auction'
              AND a.auction_date < %s
              AND a.status = 'available'
              {not_in_clause}
        """, [cutoff])
        ids_to_delete = [row[0] for row in cur.fetchall()]

    if not ids_to_delete:
        dj_messages.info(request, 'لا توجد سيارات مزاد منتهية للحذف.')
        return redirect('upload_auction_json')

    # 2. Delete in batches with raw SQL to bypass Django's collector — the
    # ORM cascade would walk reverse FKs (SiteOrder/SiteRating/...) whose
    # tables live in tenant schemas, not public, and crash here.
    deleted_count = 0
    batch_size = 200
    for i in range(0, len(ids_to_delete), batch_size):
        batch = ids_to_delete[i:i + batch_size]
        with connection.cursor() as cur:
            cur.execute(
                "DELETE FROM cars_apicar WHERE id = ANY(%s)",
                [batch],
            )
            deleted_count += cur.rowcount

    dj_messages.success(request, f'تم حذف {deleted_count} سيارة مزاد منتهية الصلاحية بنجاح.')
    return redirect('upload_auction_json')


# ── Admin: Upload Auction JSON ──

@staff_member_required
def upload_auction_json(request):
    if not _is_public_schema():
        return redirect('home')
    import json
    from datetime import datetime
    from django.core.exceptions import MultipleObjectsReturned
    from django.db import transaction
    from cars.models import Manufacturer, CarModel, CarBadge, CarColor, BodyType, Category
    from cars.normalization import normalize_transmission, normalize_fuel

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

        # Collect every unique Arabic option name across the whole feed and
        # batch-translate it once to en/ru/es. Cached in .translations_cache.json
        # so repeated uploads don't re-hit the API.
        from cars.translation_utils import translate_batch
        unique_option_ar: set[str] = set()
        for item in data:
            for name in (item.get("option") or []):
                if isinstance(name, str) and name.strip():
                    unique_option_ar.add(name.strip())
        option_translations = translate_batch(unique_option_ar, ["en", "ru", "es"], source="ar")
        
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
        seen_car_ids = set()  # track IDs seen in this upload batch to skip in-file duplicates

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

            # Autohub feeds ship a parallel `option` (Arabic names) alongside
            # `options` (objects with image URLs). Zip them so each stored
            # option carries its Arabic label plus translations pulled from
            # the cached Google Translate pass above.
            raw_options = item.get("options") or []
            raw_option_ar = item.get("option") or []
            enriched_options = []
            for idx, opt in enumerate(raw_options):
                if isinstance(opt, dict):
                    opt_copy = dict(opt)
                    if idx < len(raw_option_ar):
                        ar_name = (raw_option_ar[idx] or "").strip()
                        opt_copy["name_ar"] = ar_name
                        tr = option_translations.get(ar_name, {})
                        opt_copy["name_en"] = tr.get("en", ar_name)
                        opt_copy["name_ru"] = tr.get("ru", ar_name)
                        opt_copy["name_es"] = tr.get("es", ar_name)
                    enriched_options.append(opt_copy)

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
                "transmission": (normalize_transmission(item.get("mission_en") or item.get("mission") or "") or "")[:100],
                "power": parse_power(item.get("power")),
                "price": int(item.get("price") or 0),
                "mileage": parse_mileage(item.get("mileage")),
                "fuel": (normalize_fuel(item.get("fuel_en") or item.get("fuel") or "") or "")[:100],
                "images": item.get("images") or [],
                "inspection_image": item.get("inspection_image") or "",
                "points": str(item.get("points") or item.get("score") or "")[:50],
                "address": (item.get("region") or "")[:255],
                "seat_count": int(item.get("seats") or 0),
                "entry": item.get("entry") or "",
                "vin": car_id,
                "drive_wheel": (item.get("wheel") or "")[:100],
                "options": enriched_options,
            }
            
            # If we don't have a resolved badge, skip the row to avoid DB constraint errors
            if not badge:
                skipped += 1
                continue

            if car_id in existing_car_ids:
                cars_to_update.append(car_data)
            elif car_id in seen_car_ids:
                # Duplicate within the uploaded file — skip to avoid bulk_create IntegrityError
                skipped += 1
                continue
            else:
                seen_car_ids.add(car_id)
                cars_to_create.append(ApiCar(**car_data))

        # Bulk create new cars
        with transaction.atomic():
            if cars_to_create:
                ApiCar.objects.bulk_create(cars_to_create, batch_size=500, ignore_conflicts=True)
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
                         'address', 'vin', "seat_count", "entry", "drive_wheel", "options"],
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


@staff_member_required
def import_happycar_view(request):
    """Kick off `manage.py import_happycar` for the current tenant as a
    detached subprocess so the web request returns immediately. A single run
    per schema is tracked via the cache (`happycar_import:<schema>`); the
    subprocess's stdout/stderr stream into a /tmp log that this view tails.
    """
    if _is_public_schema():
        messages.error(request, "لا يمكن الاستيراد في مخطط 'public'.")
        return redirect('site_dashboard')

    schema = connection.schema_name
    cache_key = f"happycar_import:{schema}"
    state = cache.get(cache_key) or {}

    # Detect stale state (process exited or host rebooted). os.kill(pid, 0)
    # alone isn't enough: the subprocess we spawned with Popen+start_new_session
    # gets reparented but is never wait()'d, so on Linux/macOS it lingers as a
    # zombie that os.kill still reports as alive until the gunicorn worker exits.
    # Treat zombies/defunct states as dead, and also fall back to log-content
    # markers ("Done. " / Python tracebacks) so a stuck cache entry self-heals.
    def _pid_alive(pid):
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return False
        # Check process state — Z (zombie) / X (dead) means it finished.
        try:
            ps = subprocess.run(
                ['ps', '-p', str(pid), '-o', 'state='],
                capture_output=True, text=True, timeout=2,
            )
            state_char = (ps.stdout or '').strip()[:1]
            if state_char in ('Z', 'X'):
                return False
        except (subprocess.SubprocessError, OSError):
            pass
        return True

    def _log_indicates_finished(path):
        if not path or not os.path.exists(path):
            return False
        try:
            with open(path, 'rb') as f:
                try:
                    f.seek(-4096, os.SEEK_END)
                except OSError:
                    f.seek(0)
                tail = f.read().decode('utf-8', errors='replace')
        except OSError:
            return False
        return ('Done. ' in tail
                or 'HappyCarAuthError' in tail
                or 'CommandError' in tail
                or 'Traceback (most recent call last)' in tail)

    running = _pid_alive(state.get('pid'))
    if running and _log_indicates_finished(state.get('log_path')):
        running = False
    if state and not running:
        # Process finished — clear state so the form re-appears on next GET,
        # but keep the final log visible for this one render.
        cache.delete(cache_key)

    if request.method == 'POST':
        # Manual reset escape hatch for stuck cache entries (zombie subprocess,
        # crashed worker, etc). The cache_key value can also be cleared via the
        # Django shell, but a button is friendlier.
        if request.POST.get('action') == 'reset':
            cache.delete(cache_key)
            messages.success(request, "تم إعادة تعيين حالة الاستيراد.")
            return redirect('import_happycar')

        if running:
            messages.info(request, "استيراد جارٍ بالفعل، الرجاء الانتظار حتى ينتهي.")
            return redirect('import_happycar')

        cookie = (request.POST.get('cookie') or '').strip()
        lang = request.POST.get('lang') or 'en'
        if lang not in ('ar', 'en', 'ko'):
            lang = 'en'

        cmd = [
            sys.executable, 'manage.py', 'import_happycar',
            '--schema', schema, '--lang', lang,
        ]
        pages_raw = (request.POST.get('pages') or '').strip()
        if pages_raw:
            try:
                cmd += ['--pages', str(int(pages_raw))]
            except ValueError:
                pass
        if request.POST.get('with_gallery'):
            cmd.append('--with-gallery')
        if request.POST.get('download_images'):
            cmd.append('--download-images')
        if request.POST.get('delete_missing'):
            cmd.append('--delete-missing')
        if request.POST.get('dry_run'):
            cmd.append('--dry-run')

        env = os.environ.copy()
        if cookie:
            env['HAPPYCAR_COOKIE'] = cookie

        log_fd, log_path = tempfile.mkstemp(
            prefix=f'happycar-{schema}-', suffix='.log')
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(settings.BASE_DIR),
                stdout=log_fd, stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            os.close(log_fd)

        cache.set(cache_key, {
            'pid': proc.pid,
            'log_path': log_path,
            'started_at': time.time(),
            'cmd': ' '.join(cmd),
        }, 60 * 60 * 6)

        messages.success(request, "بدأ الاستيراد في الخلفية.")
        return redirect('import_happycar')

    # GET — render form + log tail
    log_output = ''
    if state.get('log_path') and os.path.exists(state['log_path']):
        try:
            with open(state['log_path'], 'rb') as f:
                data = f.read()
            log_output = data[-8000:].decode('utf-8', errors='replace')
        except OSError:
            pass

    elapsed = None
    if state.get('started_at'):
        elapsed = int(time.time() - state['started_at'])

    unsold_damaged_count = (SiteCar.objects
                            .filter(external_id__startswith='hc_')
                            .exclude(status='sold').count())

    return render(request, 'site_cars/import_happycar.html', {
        'schema': schema,
        'running': running,
        'elapsed': elapsed,
        'log_output': log_output,
        'cmd_preview': state.get('cmd', ''),
        'unsold_damaged_count': unsold_damaged_count,
    })


@staff_member_required
@require_POST
def delete_unsold_damaged(request):
    """Bulk-delete damaged (HappyCar-imported) SiteCars whose status is not
    'sold'. Cascades to SiteCarImage via FK; no other related models point
    at SiteCar, so this is a clean wipe of non-sold stock.
    """
    if _is_public_schema():
        messages.error(request, "غير متاح في مخطط 'public'.")
        return redirect('site_dashboard')

    qs = SiteCar.objects.filter(external_id__startswith='hc_').exclude(status='sold')
    count = qs.count()
    if count == 0:
        messages.info(request, "لا توجد سيارات مصدومة غير مباعة للحذف.")
    else:
        qs.delete()
        # Invalidate the damaged-cars tab + landing caches so the UI reflects
        # the deletion immediately instead of after TTL.
        schema = connection.schema_name
        cache.delete(f"car_list_v2:damaged_cars_count:{schema}")
        # Landing cache keys include the design, so be conservative — just
        # pattern-delete any landing entry for this schema.
        # (Django's core cache doesn't support pattern delete; rely on TTL.)
        messages.success(request, f"تم حذف {count} سيارة مصدومة غير مباعة.")
    return redirect('import_happycar')


@staff_member_required
@require_POST
def save_public_car(request, api_car_id):
    """Copy a public ApiCar into the current tenant's SiteCar inventory.

    Dedupe key: external_id='apicar_<car_id>' — mirrors the 'hc_*' pattern
    used for HappyCar imports. Cross-schema FKs aren't possible under
    django-tenants, so the string key is the link back to the public row.
    """
    if _is_public_schema():
        return redirect('home')

    api_car = get_object_or_404(
        ApiCar.objects.select_related('manufacturer', 'model', 'color', 'body'),
        pk=api_car_id,
    )
    external_id = f"apicar_{api_car.car_id}"

    existing = SiteCar.objects.filter(external_id=external_id).first()
    if existing:
        messages.info(request, 'هذه السيارة محفوظة لديك بالفعل.')
        return redirect('site_car_detail', pk=existing.pk)

    first_image = ''
    if isinstance(api_car.images, list) and api_car.images:
        first = api_car.images[0]
        if isinstance(first, str):
            first_image = first
        elif isinstance(first, dict):
            first_image = first.get('url') or first.get('image') or ''
    if not first_image and api_car.image:
        first_image = api_car.image

    site_car = SiteCar.objects.create(
        title=api_car.title or f"{api_car.manufacturer.name} {api_car.model.name} {api_car.year}",
        description=api_car.description or '',
        manufacturer=api_car.manufacturer.name,
        model=api_car.model.name,
        year=api_car.year,
        color=api_car.color.name if api_car.color_id else '',
        mileage=api_car.mileage or 0,
        price=api_car.price or 0,
        transmission=api_car.transmission or '',
        fuel=api_car.fuel or '',
        body_type=api_car.body.name if api_car.body_id else '',
        engine=api_car.engine or '',
        drive_wheel=api_car.drive_wheel or '',
        status='available',
        external_id=external_id,
        external_image_url=first_image,
        source_url='',
    )
    messages.success(request, 'تم حفظ السيارة في سياراتك.')
    return redirect('site_car_detail', pk=site_car.pk)


@staff_member_required
def invoice_new(request, pk):
    """Create a sales invoice for a SiteCar and redirect to the printable view."""
    if _is_public_schema():
        return redirect('home')

    car = get_object_or_404(SiteCar, pk=pk)

    existing_bill = car.bills.order_by('-created_at').first()
    if existing_bill is not None:
        messages.info(request, f'توجد فاتورة سابقة لهذه السيارة ({existing_bill.receipt_number}).')
        return redirect('invoice_view', pk=car.pk, bill_pk=existing_bill.pk)

    if request.method == 'POST':
        buyer_name = request.POST.get('buyer_name', '').strip()
        if not buyer_name:
            messages.error(request, 'يرجى إدخال اسم المشتري.')
            return render(request, 'site_cars/invoice_form.html', {'car': car})

        try:
            sale_price = int(request.POST.get('sale_price') or car.price)
        except ValueError:
            messages.error(request, 'السعر غير صالح.')
            return render(request, 'site_cars/invoice_form.html', {'car': car})

        sale_date_str = request.POST.get('sale_date', '').strip()
        if sale_date_str:
            from datetime import datetime
            try:
                sale_date = datetime.strptime(sale_date_str, '%Y-%m-%d').date()
            except ValueError:
                sale_date = timezone.now().date()
        else:
            sale_date = timezone.now().date()

        bill = SiteBill.objects.create(
            site_car=car,
            price=sale_price,
            date=sale_date,
            buyer_name=buyer_name,
            buyer_id_number=request.POST.get('buyer_id_number', '').strip(),
            buyer_phone=request.POST.get('buyer_phone', '').strip(),
            buyer_address=request.POST.get('buyer_address', '').strip(),
            description=request.POST.get('description', '').strip(),
            is_paid=request.POST.get('is_paid') == 'on',
        )

        if car.status != 'sold':
            car.status = 'sold'
            car.save(update_fields=['status'])

        messages.success(request, f'تم إنشاء الفاتورة {bill.receipt_number}.')
        return redirect('invoice_view', pk=car.pk, bill_pk=bill.pk)

    return render(request, 'site_cars/invoice_form.html', {'car': car})


@staff_member_required
def invoice_edit(request, pk, bill_pk):
    """Edit an existing invoice. Receipt number stays locked (auditability)."""
    if _is_public_schema():
        return redirect('home')

    car = get_object_or_404(SiteCar, pk=pk)
    bill = get_object_or_404(SiteBill, pk=bill_pk, site_car=car)

    if request.method == 'POST':
        buyer_name = request.POST.get('buyer_name', '').strip()
        if not buyer_name:
            messages.error(request, 'يرجى إدخال اسم المشتري.')
            return render(request, 'site_cars/invoice_form.html', {'car': car, 'bill': bill})

        try:
            sale_price = int(request.POST.get('sale_price') or bill.price)
        except ValueError:
            messages.error(request, 'السعر غير صالح.')
            return render(request, 'site_cars/invoice_form.html', {'car': car, 'bill': bill})

        sale_date_str = request.POST.get('sale_date', '').strip()
        if sale_date_str:
            from datetime import datetime
            try:
                bill.date = datetime.strptime(sale_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        bill.price = sale_price
        bill.buyer_name = buyer_name
        bill.buyer_id_number = request.POST.get('buyer_id_number', '').strip()
        bill.buyer_phone = request.POST.get('buyer_phone', '').strip()
        bill.buyer_address = request.POST.get('buyer_address', '').strip()
        bill.description = request.POST.get('description', '').strip()
        bill.is_paid = request.POST.get('is_paid') == 'on'
        bill.save()

        messages.success(request, 'تم تحديث الفاتورة.')
        return redirect('invoice_view', pk=car.pk, bill_pk=bill.pk)

    return render(request, 'site_cars/invoice_form.html', {'car': car, 'bill': bill})


@staff_member_required
def invoice_view(request, pk, bill_pk):
    """Render a printable invoice. Use browser print dialog for PDF export."""
    if _is_public_schema():
        return redirect('home')
    car = get_object_or_404(SiteCar, pk=pk)
    bill = get_object_or_404(SiteBill, pk=bill_pk, site_car=car)
    shipment = getattr(bill, 'shipment', None)
    return render(request, 'site_cars/invoice.html', {'car': car, 'bill': bill, 'shipment': shipment})


def public_track(request, receipt_number):
    """Public shipment tracking — no login. Buyer scans the URL off the
    printed invoice and sees status + ETA only. Tenant middleware routes
    to the right schema by hostname, so lookups stay tenant-scoped.

    Deliberately does NOT expose: buyer PII, prices, notes. Only the
    shipment/vehicle fields the buyer already knows.
    """
    if _is_public_schema():
        raise Http404()

    bill = get_object_or_404(
        SiteBill.objects.select_related('site_car'),
        receipt_number=receipt_number,
    )
    shipment = getattr(bill, 'shipment', None)
    return render(request, 'site_cars/public_track.html', {
        'bill': bill,
        'car': bill.site_car,
        'shipment': shipment,
    })


@staff_member_required
def shipment_edit(request, pk, bill_pk):
    """Create or update the shipment attached to a bill."""
    if _is_public_schema():
        return redirect('home')

    car = get_object_or_404(SiteCar, pk=pk)
    bill = get_object_or_404(SiteBill, pk=bill_pk, site_car=car)
    shipment = SiteShipment.objects.filter(bill=bill).first()

    if request.method == 'POST':
        from datetime import datetime

        def _parse_date(value):
            value = (value or '').strip()
            if not value:
                return None
            try:
                return datetime.strptime(value, '%Y-%m-%d').date()
            except ValueError:
                return None

        shipping_cost_raw = (request.POST.get('shipping_cost') or '').strip()
        try:
            shipping_cost = float(shipping_cost_raw) if shipping_cost_raw else None
        except ValueError:
            shipping_cost = None

        fields = dict(
            status=request.POST.get('status', 'preparing'),
            shipping_company=request.POST.get('shipping_company', '').strip(),
            vessel_name=request.POST.get('vessel_name', '').strip(),
            container_number=request.POST.get('container_number', '').strip(),
            bill_of_lading=request.POST.get('bill_of_lading', '').strip(),
            origin_port=request.POST.get('origin_port', '').strip(),
            destination_port=request.POST.get('destination_port', '').strip(),
            destination_country=request.POST.get('destination_country', '').strip(),
            etd=_parse_date(request.POST.get('etd')),
            eta=_parse_date(request.POST.get('eta')),
            delivered_at=_parse_date(request.POST.get('delivered_at')),
            shipping_cost=shipping_cost,
            tracking_url=request.POST.get('tracking_url', '').strip(),
            notes=request.POST.get('notes', '').strip(),
        )

        if shipment is None:
            shipment = SiteShipment.objects.create(bill=bill, **fields)
            messages.success(request, 'تم إنشاء الشحنة.')
        else:
            for key, value in fields.items():
                setattr(shipment, key, value)
            shipment.save()
            messages.success(request, 'تم تحديث الشحنة.')

        return redirect('invoice_view', pk=car.pk, bill_pk=bill.pk)

    return render(request, 'site_cars/shipment_form.html', {
        'car': car,
        'bill': bill,
        'shipment': shipment,
        'status_choices': SiteShipment.STATUS_CHOICES,
    })


# ── Staff list pages (replacing Django admin for tenant staff) ─────────────

@staff_member_required
def staff_orders(request):
    """Tenant-side orders list with filters and inline status update."""
    if _is_public_schema():
        return redirect('home')

    qs = SiteOrder.objects.select_related('car', 'user').all()
    status = (request.GET.get('status') or '').strip()
    if status in dict(SiteOrder.STATUS_CHOICES):
        qs = qs.filter(status=status)
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(
            Q(user__username__icontains=q)
            | Q(user__email__icontains=q)
            | Q(notes__icontains=q)
            | Q(admin_notes__icontains=q)
        )

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'site_cars/staff_orders.html', {
        'page': page,
        'status': status,
        'q': q,
        'status_choices': SiteOrder.STATUS_CHOICES,
    })


@staff_member_required
@require_POST
def staff_order_update(request, pk):
    if _is_public_schema():
        return redirect('home')
    order = get_object_or_404(SiteOrder, pk=pk)
    new_status = request.POST.get('status', '').strip()
    if new_status in dict(SiteOrder.STATUS_CHOICES):
        order.status = new_status
        if new_status == 'completed' and not order.completed_at:
            order.completed_at = timezone.now()
    order.admin_notes = request.POST.get('admin_notes', order.admin_notes)
    order.save()
    messages.success(request, f'تم تحديث الطلب #{order.pk}.')
    return redirect('staff_orders')


@staff_member_required
def staff_ratings(request):
    """Tenant-side ratings list. Approve/reject use existing views."""
    if _is_public_schema():
        return redirect('home')

    qs = SiteRating.objects.select_related('car', 'user').all()
    status = (request.GET.get('status') or 'pending').strip()
    if status == 'pending':
        qs = qs.filter(is_approved=False)
    elif status == 'approved':
        qs = qs.filter(is_approved=True)
    # 'all' → no filter

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'site_cars/staff_ratings.html', {
        'page': page,
        'status': status,
    })


@staff_member_required
def staff_questions(request):
    """Tenant-side questions list."""
    if _is_public_schema():
        return redirect('home')

    qs = SiteQuestion.objects.select_related('car', 'user').all()
    status = (request.GET.get('status') or 'pending').strip()
    if status == 'pending':
        qs = qs.filter(is_answered=False)
    elif status == 'answered':
        qs = qs.filter(is_answered=True)

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'site_cars/staff_questions.html', {
        'page': page,
        'status': status,
    })


@staff_member_required
@require_POST
def staff_question_answer(request, pk):
    if _is_public_schema():
        return redirect('home')
    question = get_object_or_404(SiteQuestion, pk=pk)
    answer = (request.POST.get('answer') or '').strip()
    if answer:
        question.answer = answer
        question.is_answered = True
        question.save()
        messages.success(request, 'تم إرسال الإجابة.')
    else:
        messages.error(request, 'الرجاء إدخال إجابة.')
    return redirect('staff_questions')


# ── SaaS-owner dashboard (public schema only) ──────────────────────────────

def _saas_owner_dashboard(request):
    """Overview of every tenant: subscription status + monthly revenue."""
    from tenants.models import Tenant
    from billing.models import Subscription

    now = timezone.now()
    tenants = (
        Tenant.objects.exclude(schema_name="public")
        .prefetch_related("domains")
        .order_by("name")
    )
    subs_by_tenant = {
        s.tenant_id: s for s in Subscription.objects.all()
    }

    rows = []
    active_count = 0
    overdue_count = 0
    none_count = 0
    monthly_revenue = 0  # sum of billing_amount_usd for tenants with active subs

    for t in tenants:
        sub = subs_by_tenant.get(t.id)
        is_active = bool(sub and sub.is_active)
        if is_active:
            active_count += 1
            monthly_revenue += float(t.billing_amount_usd or 0)
        elif sub and sub.current_period_end and sub.current_period_end < now:
            overdue_count += 1
        else:
            none_count += 1

        primary_domain = t.domains.first()
        rows.append({
            "tenant": t,
            "subscription": sub,
            "is_active": is_active,
            "primary_domain": primary_domain.domain if primary_domain else None,
        })

    return render(request, "site_cars/saas_dashboard.html", {
        "rows": rows,
        "total_tenants": len(rows),
        "active_count": active_count,
        "overdue_count": overdue_count,
        "none_count": none_count,
        "monthly_revenue": monthly_revenue,
    })
