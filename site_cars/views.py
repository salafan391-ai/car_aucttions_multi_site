import os
import subprocess
import sys
import tempfile
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Avg, Sum, Count, Q, F, Func, Value, CharField
from django.http import Http404, JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from cars.models import ApiCar, Manufacturer, CarModel
from .models import SiteCar, SiteCarImage, SiteOrder, SiteBill, SiteBillItem, SiteReceipt, SiteShipment, SiteRating, SiteQuestion, SiteSoldCar, SiteMessage, SiteEmailLog, SiteFaq, UserProfile
from .models import damaged_auction_ended, damaged_qs, exclude_expired_damaged, own_qs
from .permissions import section_required, site_admin_required, staff_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from cars.models import Wishlist
from .image_utils import optimize_image, batch_optimize_images


def _is_public_schema():
    return connection.schema_name == 'public'


def _bust_home_cache():
    """Drop the cached home + landing so a just-approved rating (or other
    homepage change) appears immediately for this tenant. The keys carry a
    catalog-filter signature suffix, so clear every variant by pattern."""
    schema = getattr(connection, 'schema_name', 'public')
    try:
        if hasattr(cache, 'delete_pattern'):
            for _p in (f"home_html_v9:{schema}*", f"home_ctx_v9:{schema}*", f"landing_html:{schema}*"):
                cache.delete_pattern(_p)
            return
    except Exception:
        pass
    cache.delete(f"home_html_v9:{schema}")
    cache.delete(f"home_ctx_v9:{schema}")


@staff_required
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
    try:
        from site_shop.models import ShopRequest
        context['shop_requests_unhandled'] = ShopRequest.objects.filter(is_handled=False).count()
    except Exception:
        context['shop_requests_unhandled'] = 0

    # Google Search Console metrics for this tenant's primary domain (cached, best-effort).
    try:
        from django.db import connection
        from tenants.gsc import get_search_metrics
        _dom = connection.tenant.get_primary_domain()
        context['gsc'] = get_search_metrics(_dom.domain) if _dom else None
    except Exception:
        context['gsc'] = None

    # This tenant's own site traffic (from the request counter).
    try:
        from django.db import connection
        from tenants.metrics import tenant_traffic
        context['traffic'] = tenant_traffic(getattr(connection, 'schema_name', 'public'))
    except Exception:
        context['traffic'] = None

    return render(request, 'site_cars/dashboard.html', context)


def site_car_list(request):
    if _is_public_schema():
        return redirect('home')

    # Primary tab — "mine" (admin-uploaded) vs. "auctions" (imported cars
    # whose external_id starts with 'hc_' e.g. from HappyCar).
    source = request.GET.get('source', 'mine')  # 'mine' | 'auctions'
    # Damaged cars drop off the list once their auction ends, the same way
    # expired auction cars drop off /cars/.
    external_qs = exclude_expired_damaged(damaged_qs())
    if source == 'auctions':
        base_qs = external_qs
    else:
        base_qs = own_qs()
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
    if v := _pick('model'):
        qs = qs.filter(model__iexact=v)
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
    mine_total = own_qs().count()

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


@section_required("cars")
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
            currency=(request.POST.get('currency') or 'KRW').upper(),
            transmission=request.POST.get('transmission', ''),
            fuel=request.POST.get('fuel', ''),
            body_type=request.POST.get('body_type', ''),
            engine=request.POST.get('engine', ''),
            drive_wheel=request.POST.get('drive_wheel', ''),
            status=request.POST.get('status', 'available'),
            is_featured=request.POST.get('is_featured') == 'on',
            vin=(request.POST.get('vin') or '').strip() or None,
            plate_number=(request.POST.get('plate_number') or '').strip() or None,
            inspection_video_url=(request.POST.get('inspection_video_url') or '').strip() or None,
        )
        
        # Handle main image with optimization
        if 'image' in request.FILES:
            car.image = optimize_image(request.FILES['image'])
            car.save()
        
        # Handle inspection image
        if 'inspection_image' in request.FILES:
            car.inspection_image = optimize_image(request.FILES['inspection_image'])
            car.save()

        # Handle inspection video (stored on external object storage; no image optimization)
        if 'inspection_video' in request.FILES:
            car.inspection_video = request.FILES['inspection_video']
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


@section_required("cars")
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
        car.currency = (request.POST.get('currency') or car.currency or 'KRW').upper()
        car.transmission = request.POST.get('transmission', car.transmission)
        car.fuel = request.POST.get('fuel', car.fuel)
        car.body_type = request.POST.get('body_type', car.body_type)
        car.engine = request.POST.get('engine', car.engine)
        car.drive_wheel = request.POST.get('drive_wheel', car.drive_wheel)
        car.status = request.POST.get('status', car.status)
        car.is_featured = request.POST.get('is_featured') == 'on'
        car.vin = (request.POST.get('vin') or '').strip() or None
        car.plate_number = (request.POST.get('plate_number') or '').strip() or None
        car.inspection_video_url = (request.POST.get('inspection_video_url') or '').strip() or None

        # Handle main image with optimization
        if 'image' in request.FILES:
            car.image = optimize_image(request.FILES['image'])

        # Handle inspection image
        if 'inspection_image' in request.FILES:
            car.inspection_image = optimize_image(request.FILES['inspection_image'])

        # Handle inspection video (external storage; no optimization)
        if 'inspection_video' in request.FILES:
            car.inspection_video = request.FILES['inspection_video']

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


@section_required("cars")
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


@section_required("cars")
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


@section_required("cars")
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

    # Once a damaged car's auction ends, hide its detail page — the same rule
    # cars.views.car_detail applies to expired auction cars. Staff keep access
    # so they can still manage the row, and ?archived=1 leaves an escape hatch.
    if (damaged_auction_ended(car)
            and request.GET.get('archived') != '1' and not request.user.is_staff):
        raise Http404("auction ended")

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
    invoices = (
        SiteBill.objects.filter(buyer_user=request.user)
        .prefetch_related('items__site_car').order_by('-date')
    )
    return render(request, 'site_cars/my_orders.html', {'orders': orders, 'invoices': invoices})


@login_required
def account_view(request):
    """User profile / account page: edit info, change password, quick links."""
    if _is_public_schema():
        return redirect('home')
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    pw_form = PasswordChangeForm(request.user)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'info':
            u = request.user
            u.first_name = (request.POST.get('first_name') or '').strip()
            u.last_name = (request.POST.get('last_name') or '').strip()
            u.email = (request.POST.get('email') or '').strip()
            u.save()
            profile.phone = (request.POST.get('phone') or '').strip()
            if request.FILES.get('avatar'):
                profile.avatar = request.FILES['avatar']
            profile.save()
            messages.success(request, 'تم تحديث معلوماتك بنجاح.')
            return redirect('account')
        elif action == 'password':
            pw_form = PasswordChangeForm(request.user, request.POST)
            if pw_form.is_valid():
                pw_form.save()
                update_session_auth_hash(request, pw_form.user)  # stay logged in
                messages.success(request, 'تم تغيير كلمة المرور بنجاح.')
                return redirect('account')
            else:
                messages.error(request, 'تعذّر تغيير كلمة المرور، تحقّق من الحقول.')
    ctx = {
        'profile': profile,
        'pw_form': pw_form,
        'wishlist_count': Wishlist.objects.filter(session_key=request.session.session_key).count() if request.session.session_key else 0,
        'orders_count': SiteOrder.objects.filter(user=request.user).count(),
        'unread_count': SiteMessage.objects.filter(recipient=request.user, is_read=False).count(),
    }
    return render(request, 'site_cars/account.html', ctx)


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
            return redirect('car_detail', slug=car.slug)

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

    return redirect('car_detail', slug=car.slug)


def rate_site(request):
    """Rate the website itself (not a specific car). No login required; if the
    visitor is logged in the rating is linked to their account (one per user),
    otherwise it's stored anonymously with the name they enter."""
    if _is_public_schema():
        return redirect('home')

    back = request.META.get('HTTP_REFERER') or reverse('home')
    if request.method == 'POST':
        rating_val = request.POST.get('rating', '').strip()
        comment = request.POST.get('comment', '').strip()
        name = request.POST.get('name', '').strip()[:120]
        if not rating_val or not rating_val.isdigit() or int(rating_val) not in range(1, 6):
            messages.error(request, 'يرجى اختيار تقييم من 1 إلى 5.')
            return redirect(back)

        if request.user.is_authenticated:
            # Linked to the account — keep one website rating per user.
            display_name = name or request.user.get_full_name() or request.user.get_username()
            SiteRating.objects.update_or_create(
                user=request.user, car=None,
                defaults={'rating': int(rating_val), 'comment': comment,
                          'name': display_name, 'is_approved': False},
            )
        else:
            if not name:
                messages.error(request, 'يرجى إدخال الاسم.')
                return redirect(back)
            SiteRating.objects.create(
                user=None, car=None, name=name,
                rating=int(rating_val), comment=comment, is_approved=False,
            )
        messages.success(request, 'شكراً لتقييمك! سيظهر بعد مراجعة المشرف.')
    return redirect(back)


def faq(request):
    """Public FAQ page: published entries + a visitor 'ask a question' form.
    Submitted questions arrive unpublished/unanswered for the admin to handle."""
    if _is_public_schema():
        return redirect('home')

    if request.method == 'POST':
        q = (request.POST.get('question') or '').strip()
        name = (request.POST.get('name') or '').strip()
        if not q:
            messages.error(request, 'يرجى كتابة سؤالك.')
        else:
            SiteFaq.objects.create(
                question=q[:2000],
                submitter_name=name[:120],
                is_user_submitted=True,
                is_published=False,
            )
            messages.success(request, 'تم إرسال سؤالك! سيظهر بعد مراجعة وإجابة المشرف.')
        return redirect('faq')

    faqs = SiteFaq.objects.filter(is_published=True)
    return render(request, 'site_cars/faq.html', {'faqs': faqs})


@section_required("reviews")
def faq_manage(request):
    """Dashboard FAQ manager: add admin Q&A, answer/publish visitor questions."""
    if _is_public_schema():
        return redirect('home')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add':
            q = (request.POST.get('question') or '').strip()
            a = (request.POST.get('answer') or '').strip()
            if q:
                try:
                    order = int(request.POST.get('order') or 0)
                except ValueError:
                    order = 0
                SiteFaq.objects.create(question=q, answer=a, is_published=True, order=order)
                messages.success(request, 'تمت إضافة السؤال.')
        elif action == 'update':
            obj = get_object_or_404(SiteFaq, pk=request.POST.get('id'))
            obj.question = (request.POST.get('question') or obj.question).strip()
            obj.answer = (request.POST.get('answer') or '').strip()
            obj.is_published = 'is_published' in request.POST
            try:
                obj.order = int(request.POST.get('order') or 0)
            except ValueError:
                pass
            obj.save()
            messages.success(request, 'تم حفظ التغييرات.')
        elif action == 'delete':
            SiteFaq.objects.filter(pk=request.POST.get('id')).delete()
            messages.success(request, 'تم حذف السؤال.')
        return redirect('faq_manage')

    pending = SiteFaq.objects.filter(is_published=False)
    published = SiteFaq.objects.filter(is_published=True)
    return render(request, 'site_cars/faq_manage.html', {
        'pending': pending,
        'published': published,
    })


# POST-only: both of these change state and `reject_rating` deletes permanently.
# As GET links they were reachable by anything that follows a URL while an admin
# is logged in — a browser prefetcher, a link scanner, a chat client unfurling a
# pasted link — and carried no CSRF protection. @require_POST + {% csrf_token %}
# in the templates closes both holes.
@require_POST
@section_required("reviews")
def approve_rating(request, pk):
    """Approve a rating (POST only)."""
    if _is_public_schema():
        return redirect('home')

    rating = get_object_or_404(SiteRating, pk=pk)
    rating.is_approved = True
    rating.save()
    _bust_home_cache()  # show it on the homepage right away
    messages.success(request, f'تم الموافقة على تقييم {rating.display_name}')

    # Redirect back to the referrer, else the car page (per-car rating) or the
    # staff ratings list (website rating has no car).
    fallback = reverse('car_detail', kwargs={'slug': rating.car.slug}) if rating.car else reverse('staff_ratings')
    return redirect(request.META.get('HTTP_REFERER') or fallback)


@require_POST
@section_required("reviews")
def reject_rating(request, pk):
    """Reject and permanently delete a rating (POST only)."""
    if _is_public_schema():
        return redirect('home')

    rating = get_object_or_404(SiteRating, pk=pk)
    car_slug = rating.car.slug if rating.car else None
    name = rating.display_name
    rating.delete()
    _bust_home_cache()  # remove it from the homepage right away
    messages.success(request, f'تم رفض وحذف تقييم {name}')

    # Redirect back to the referrer, else the car page or the staff ratings list.
    fallback = reverse('car_detail', kwargs={'slug': car_slug}) if car_slug else reverse('staff_ratings')
    return redirect(request.META.get('HTTP_REFERER') or fallback)


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

@site_admin_required
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
@section_required("cars")
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

@section_required("cars")
def upload_auction_json(request):
    if not _is_public_schema():
        return redirect('home')
    import json
    from datetime import datetime
    from django.core.exceptions import MultipleObjectsReturned
    from django.db import transaction
    from cars.models import Manufacturer, CarModel, CarBadge, CarColor, BodyType, Category
    from cars.normalization import normalize_transmission, normalize_fuel, normalize_name

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

            # Normalize names up front so dict keys match the DB's stored form
            # (lowercase, via Manufacturer/CarModel.save() → normalize_name).
            # Without this, the JSON's "Kia" misses the dict's "kia" key and we
            # bulk_create a fresh row with capital K each run.
            make_name = normalize_name(item.get("make_en") or item.get("make")) or "unknown"
            model_name = normalize_name(item.get("models_en") or item.get("models")) or "unknown"
            color_name = normalize_name(item.get("color_en") or item.get("color")) or "unknown"

            # Handle manufacturer
            if make_name not in all_manufacturers and make_name not in new_manufacturers:
                new_manufacturers[make_name] = Manufacturer(name=make_name, country="Unknown")
            manufacturer = all_manufacturers.get(make_name) or new_manufacturers.get(make_name)

            # Handle model — key by (normalized name, make_name) so same model
            # name under two different makes both get staged.
            model_stage_key = (model_name, make_name)
            model_lookup_key = (model_name, manufacturer.id if hasattr(manufacturer, 'id') and manufacturer.id else None)
            if model_lookup_key not in all_models and model_stage_key not in new_models:
                new_models[model_stage_key] = (model_name, make_name)

            # Handle color
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
        
       
        # Bulk create missing models. Re-check all_models for each pair before
        # appending — same (name, mfr_id) may already have landed in all_models
        # from a previous batch in this same run.
        if new_models:
            models_to_create = []
            for model_name, make_name in new_models.values():
                manufacturer_obj = all_manufacturers.get(make_name)
                if manufacturer_obj and (model_name, manufacturer_obj.id) not in all_models:
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

            # Same normalization as the first loop — the dict lookups below need
            # to match the lowercased keys we built.
            make_name = normalize_name(item.get("make_en") or item.get("make")) or "unknown"
            model_name = normalize_name(item.get("models_en") or item.get("models")) or "unknown"
            manufacturer = all_manufacturers.get(make_name)

            model_key = (model_name, manufacturer.id if manufacturer else None)
            car_model = all_models.get(model_key)
            # If model is missing but we have a manufacturer, create or reuse an
            # 'unknown' model for this manufacturer to allow creating a badge.
            if not car_model and manufacturer:
                unknown_model_key = ("unknown", manufacturer.id)
                car_model = all_models.get(unknown_model_key)
                if not car_model:
                    car_model = CarModel.objects.create(name='unknown', manufacturer=manufacturer)
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

            color_name = normalize_name(item.get("color_en") or item.get("color")) or "unknown"
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


@section_required("cars")
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

        # HappyCar login: store the username/password on the tenant so they're
        # reused on every future run. The password field is left blank to keep
        # the saved one; a new value replaces it.
        from tenants.models import Tenant
        tenant_obj = Tenant.objects.filter(schema_name=schema).first()
        hc_user = (request.POST.get('happycar_username') or '').strip()
        hc_pass = request.POST.get('happycar_password') or ''
        if tenant_obj is not None:
            fields = []
            if hc_user != (tenant_obj.happycar_username or ''):
                tenant_obj.happycar_username = hc_user
                fields.append('happycar_username')
            if hc_pass:  # only overwrite when a new password is entered
                tenant_obj.happycar_password = hc_pass
                fields.append('happycar_password')
            if fields:
                tenant_obj.save(update_fields=fields)
            hc_user = tenant_obj.happycar_username
            hc_pass = tenant_obj.happycar_password

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

        # Pass THIS tenant's credentials (never inherit a global cookie/creds
        # from the environment, so one tenant can't import with another's login).
        env = os.environ.copy()
        env.pop('HAPPYCAR_COOKIE', None)
        if hc_user and hc_pass:
            env['HAPPYCAR_USER'] = hc_user
            env['HAPPYCAR_PASS'] = hc_pass
        else:
            env.pop('HAPPYCAR_USER', None)
            env.pop('HAPPYCAR_PASS', None)

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

    from tenants.models import Tenant
    _t = Tenant.objects.filter(schema_name=schema).first()

    return render(request, 'site_cars/import_happycar.html', {
        'schema': schema,
        'running': running,
        'elapsed': elapsed,
        'log_output': log_output,
        'cmd_preview': state.get('cmd', ''),
        'unsold_damaged_count': unsold_damaged_count,
        'happycar_username': (_t.happycar_username if _t else ''),
        'happycar_has_password': bool(_t and _t.happycar_password),
    })


@section_required("cars")
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


def _collect_protected_auction_car_ids():
    """Return the set of ApiCar ids referenced by ANY tenant's orders, sales,
    ratings or questions. ApiCar is a SHARED model, but these references live
    in each tenant's own schema, so a plain ORM cascade can't see them and the
    shared-row delete would raise a cross-schema FK violation. We protect every
    referenced id — mirroring the delete_expired_auctions management command.
    """
    from django_tenants.utils import schema_context, get_public_schema_name
    from tenants.models import Tenant

    protected = set()
    public = get_public_schema_name()
    for tenant in Tenant.objects.exclude(schema_name=public):
        with schema_context(tenant.schema_name):
            protected.update(SiteOrder.objects.values_list('car_id', flat=True))
            protected.update(SiteSoldCar.objects.values_list('car_id', flat=True))
            protected.update(SiteRating.objects.values_list('car_id', flat=True))
            protected.update(
                SiteQuestion.objects.exclude(car_id=None).values_list('car_id', flat=True)
            )
    return protected


@staff_required
def delete_auctions(request):
    """Owner-only tool: filter auction cars by auction name + date and bulk-delete.

    These are shared ApiCar rows, so a delete removes the cars from EVERY tenant
    site. It is therefore restricted to the PUBLIC (owner) dashboard and the
    superadmin — never exposed to individual tenants. Only `status='available'`
    auctions are deletable, and any car referenced by an order/sale/rating/
    question (in any tenant) is protected to avoid data loss and cross-schema FK
    errors. The actual delete runs inside a tenant schema so cascades resolve.
    """
    from django.utils.dateparse import parse_date

    # Platform-wide operation: owner dashboard (public schema) + superuser only.
    if not _is_public_schema() or not request.user.is_superuser:
        messages.error(request, "هذه الأداة متاحة فقط للمشرف العام من اللوحة الرئيسية.")
        return redirect('site_dashboard')

    # Auction cars only (category 'auction' with a named auction house).
    base = ApiCar.objects.filter(category__name='auction').exclude(
        auction_name__isnull=True
    ).exclude(auction_name='')

    auction_names = list(
        base.values_list('auction_name', flat=True).distinct().order_by('auction_name')
    )

    src = request.POST if request.method == 'POST' else request.GET
    sel_name = (src.get('auction_name') or '').strip()
    sel_op = (src.get('date_op') or 'before').strip() or 'before'
    sel_from = (src.get('date_from') or '').strip()
    sel_to = (src.get('date_to') or '').strip()

    def _apply_filters(qs):
        if sel_name:
            qs = qs.filter(auction_name=sel_name)
        d_from = parse_date(sel_from) if sel_from else None
        d_to = parse_date(sel_to) if sel_to else None
        if sel_op == 'before' and d_from:
            qs = qs.filter(auction_date__date__lt=d_from)
        elif sel_op == 'after' and d_from:
            qs = qs.filter(auction_date__date__gt=d_from)
        elif sel_op == 'between' and d_from and d_to:
            qs = qs.filter(auction_date__date__gte=d_from, auction_date__date__lte=d_to)
        return qs

    # Require at least one filter so we never offer a "delete every auction" path.
    if sel_op == 'between':
        has_filter = bool(sel_name) or (bool(sel_from) and bool(sel_to))
    else:
        has_filter = bool(sel_name) or bool(sel_from)

    # Only available auctions are ever deletable; sold/pending are kept.
    deletable = _apply_filters(base.filter(status='available'))

    if request.method == 'POST':
        if not has_filter:
            messages.error(request, 'حدد فلتراً واحداً على الأقل (اسم المزاد أو التاريخ) قبل الحذف.')
            return redirect('delete_auctions')

        # ── Reschedule: set a new end time for every matched auction car ──
        if src.get('action') == 'reschedule':
            from django.utils.dateparse import parse_datetime
            from django.utils import timezone as _tz
            raw = (src.get('new_datetime') or '').strip()
            new_dt = parse_datetime(raw) if raw else None
            if new_dt is None:
                messages.error(request, 'أدخل موعد الانتهاء الجديد.')
                return redirect('delete_auctions')
            if _tz.is_naive(new_dt):
                new_dt = _tz.make_aware(new_dt)
            count = deletable.update(auction_date=new_dt)
            messages.success(
                request,
                f'تم تحديث موعد انتهاء {count} سيارة مزاد إلى {new_dt:%Y-%m-%d %H:%M} (على مستوى جميع المواقع).'
            )
            return redirect('delete_auctions')

        if src.get('confirm') != 'DELETE':
            messages.error(request, 'لم يتم تأكيد الحذف. اكتب DELETE في خانة التأكيد.')
            return redirect('delete_auctions')

        from django_tenants.utils import schema_context, get_public_schema_name
        from tenants.models import Tenant

        protected = _collect_protected_auction_car_ids()
        target_ids = list(deletable.exclude(id__in=protected).values_list('id', flat=True))
        count = len(target_ids)
        skipped = deletable.filter(id__in=protected).count()
        if count == 0:
            messages.warning(
                request,
                'لا توجد سيارات قابلة للحذف بهذا الفلتر (قد تكون محمية بسبب ارتباطها بطلبات أو مبيعات).'
            )
            return redirect('delete_auctions')

        # ApiCar is shared, but its FK referencers (SiteOrder/SiteSoldCar/…) live in
        # tenant schemas that don't exist in 'public'. Run the delete inside a tenant
        # schema so Django's cascade collector can resolve those tables. The targets
        # carry no references in any tenant (all protected ids are excluded), so the
        # cascade is a no-op for tenant data and simply clears the shared rows.
        worker = Tenant.objects.exclude(schema_name=get_public_schema_name()).first()
        if worker is None:
            messages.error(request, 'لا توجد مواقع لتنفيذ الحذف.')
            return redirect('delete_auctions')
        with schema_context(worker.schema_name):
            ApiCar.objects.filter(id__in=target_ids).delete()

        msg = f'تم حذف {count} سيارة مزاد (على مستوى جميع المواقع).'
        if skipped:
            msg += f' وتم تجاوز {skipped} لارتباطها بطلبات/مبيعات.'
        messages.success(request, msg)
        return redirect('delete_auctions')

    # GET — build an accurate preview (count + sample) when a filter is set.
    preview_count = None
    skipped_count = 0
    sample = []
    if has_filter:
        protected = _collect_protected_auction_car_ids()
        target = deletable.exclude(id__in=protected)
        preview_count = target.count()
        skipped_count = deletable.filter(id__in=protected).count()
        sample = list(
            target.select_related('manufacturer', 'model').order_by('auction_date')[:25]
        )

    context = {
        'auction_names': auction_names,
        'sel_name': sel_name,
        'sel_op': sel_op,
        'sel_from': sel_from,
        'sel_to': sel_to,
        'has_filter': has_filter,
        'preview_count': preview_count,
        'skipped_count': skipped_count,
        'sample': sample,
        'total_auctions': base.count(),
    }
    return render(request, 'site_cars/delete_auctions.html', context)


@section_required("cars")
def auction_browse(request):
    """
    Dashboard view: browse all auction ApiCars (including expired) so the
    tenant can pull them into their own SiteCar inventory.

    Filters via GET params:
      - auction_date  (YYYY-MM-DD)  → exact date match
      - auction_name  (string)      → exact match (dropdown from distinct values)
      - entry         (string)      → icontains on ApiCar.entry
      - q             (string)      → icontains on title / manufacturer / model
    """
    if _is_public_schema():
        return redirect('home')

    qs = (
        ApiCar.objects
        .filter(category__name='auction')
        .select_related('manufacturer', 'model', 'color', 'body')
        .order_by('-auction_date', '-created_at')
    )

    auction_date = (request.GET.get('auction_date') or '').strip()
    auction_name = (request.GET.get('auction_name') or '').strip()
    entry = (request.GET.get('entry') or '').strip()
    q = (request.GET.get('q') or '').strip()

    if auction_date:
        qs = qs.filter(auction_date__date=auction_date)
    if auction_name:
        qs = qs.filter(auction_name=auction_name)
    if entry:
        # Accept one OR many entries (comma / space / newline / semicolon
        # separated) and match leading-zero-insensitively, so "0123", "00123"
        # and "123" are all treated as the same entry.
        import re as _re
        _tokens = [t for t in _re.split(r"[\s,;]+", entry) if t]
        _norm = list({t.lstrip("0") for t in _tokens})  # strip leading zeros each side
        qs = qs.annotate(
            _entry_norm=Func(F("entry"), Value("0"), function="LTRIM", output_field=CharField())
        ).filter(_entry_norm__in=_norm)
    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(manufacturer__name__icontains=q)
            | Q(model__name__icontains=q)
            | Q(lot_number__icontains=q)
        )

    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Mark which cars are already saved in this tenant's SiteCar inventory.
    saved_keys = set(
        SiteCar.objects
        .filter(external_id__startswith='apicar_')
        .values_list('external_id', flat=True)
    )

    # Distinct auction names for the filter dropdown — drop blanks, alpha order.
    auction_names = list(
        ApiCar.objects
        .filter(category__name='auction')
        .exclude(auction_name__isnull=True)
        .exclude(auction_name='')
        .values_list('auction_name', flat=True)
        .distinct()
        .order_by('auction_name')
    )

    # Distinct auction dates (date-truncated) — newest first.
    auction_dates = list(
        ApiCar.objects
        .filter(category__name='auction', auction_date__isnull=False)
        .dates('auction_date', 'day', order='DESC')
    )

    return render(request, 'site_cars/auction_browse.html', {
        'page_obj': page_obj,
        'cars': page_obj.object_list,
        'auction_names': auction_names,
        'auction_dates': auction_dates,
        'saved_keys': saved_keys,
        'filters': {
            'auction_date': auction_date,
            'auction_name': auction_name,
            'entry': entry,
            'q': q,
        },
        'now': timezone.now(),
    })


@section_required("cars")
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

    def _img_url(item):
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, dict):
            return (item.get('url') or item.get('image') or '').strip()
        return ''

    # ApiCar.images holds the car's whole photo set (20-80 shots) — carry all of
    # them over, not just the cover.
    image_urls = []
    if isinstance(api_car.images, list):
        for item in api_car.images:
            url = _img_url(item)
            if url and len(url) <= 500 and url not in image_urls:
                image_urls.append(url)
    if not image_urls and api_car.image:
        image_urls = [api_car.image]
    first_image = image_urls[0] if image_urls else ''

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
        vin=(api_car.vin or '').strip() or None,
        plate_number=(api_car.plate_number or '').strip() or None,
    )
    if image_urls:
        SiteCarImage.objects.bulk_create(
            [SiteCarImage(car=site_car, image_url=u, order=i) for i, u in enumerate(image_urls)],
            batch_size=100,
        )
    messages.success(request, 'تم حفظ السيارة في سياراتك.')
    return redirect('site_car_detail', pk=site_car.pk)


@section_required("sales")
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
        # First line item (more cars can be added on the edit page).
        SiteBillItem.objects.create(bill=bill, site_car=car, title=car.title, price=sale_price)

        if car.status != 'sold':
            car.status = 'sold'
            car.save(update_fields=['status'])

        messages.success(request, f'تم إنشاء الفاتورة {bill.receipt_number}.')
        return redirect('invoice_view', pk=car.pk, bill_pk=bill.pk)

    return render(request, 'site_cars/invoice_form.html', {'car': car})


@section_required("sales")
def invoice_edit(request, pk, bill_pk):
    """Edit an existing invoice. Receipt number stays locked (auditability)."""
    if _is_public_schema():
        return redirect('home')

    car = get_object_or_404(SiteCar, pk=pk)
    bill = get_object_or_404(SiteBill, pk=bill_pk, site_car=car)

    if request.method == 'POST':
        # ── Remove a line item ──
        if request.POST.get('delete_item_id'):
            if bill.items.count() <= 1:
                messages.error(request, 'لا يمكن حذف البند الوحيد في الفاتورة.')
            else:
                SiteBillItem.objects.filter(pk=request.POST.get('delete_item_id'), bill=bill).delete()
                bill.recalc_total()
                messages.success(request, 'تم حذف البند.')
            return redirect('invoice_edit', pk=car.pk, bill_pk=bill.pk)

        # ── Add another car as a line item ──
        if request.POST.get('do_add'):
            sc = SiteCar.objects.filter(pk=request.POST.get('site_car_id') or 0).first()
            if sc is None:
                messages.error(request, 'اختر سيارة صحيحة.')
            else:
                try:
                    item_price = int(request.POST.get('item_price') or sc.price or 0)
                except ValueError:
                    item_price = int(sc.price or 0)
                SiteBillItem.objects.create(bill=bill, site_car=sc, title=sc.title, price=item_price)
                if sc.status != 'sold':
                    sc.status = 'sold'
                    sc.save(update_fields=['status'])
                bill.recalc_total()
                messages.success(request, 'تمت إضافة السيارة إلى الفاتورة.')
            return redirect('invoice_edit', pk=car.pk, bill_pk=bill.pk)

        # ── Save buyer info + customer link + item prices ──
        # Resolve / detach the customer account.
        if request.POST.get('detach_user'):
            bill.buyer_user = None
        q = (request.POST.get('buyer_user_query') or '').strip()
        if q:
            from django.contrib.auth.models import User
            u = (User.objects.filter(username__iexact=q).first()
                 or User.objects.filter(email__iexact=q).first())
            if u:
                bill.buyer_user = u
            else:
                messages.warning(request, f'لم يُعثر على حساب مطابق لـ «{q}»؛ سيتم استخدام بيانات المشتري المُدخلة.')

        buyer_name = request.POST.get('buyer_name', '').strip()
        if not buyer_name and not bill.buyer_user_id:
            messages.error(request, 'يرجى إدخال اسم المشتري أو ربط حساب عميل.')
            return redirect('invoice_edit', pk=car.pk, bill_pk=bill.pk)

        sale_date_str = request.POST.get('sale_date', '').strip()
        if sale_date_str:
            from datetime import datetime
            try:
                bill.date = datetime.strptime(sale_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        # Per-item price edits (item_price_<id>).
        for item in bill.items.all():
            raw = request.POST.get(f'item_price_{item.id}')
            if raw is not None and str(raw).strip() != '':
                try:
                    item.price = int(raw)
                    item.save(update_fields=['price'])
                except ValueError:
                    pass

        bill.buyer_name = buyer_name
        bill.buyer_id_number = request.POST.get('buyer_id_number', '').strip()
        bill.buyer_phone = request.POST.get('buyer_phone', '').strip()
        bill.buyer_address = request.POST.get('buyer_address', '').strip()
        bill.description = request.POST.get('description', '').strip()
        bill.is_paid = request.POST.get('is_paid') == 'on'
        bill.save()
        bill.recalc_total()

        messages.success(request, 'تم تحديث الفاتورة.')
        return redirect('invoice_view', pk=car.pk, bill_pk=bill.pk)

    used_ids = list(bill.items.values_list('site_car_id', flat=True))
    addable_cars = SiteCar.objects.exclude(pk__in=[i for i in used_ids if i]).order_by('-created_at')[:300]
    return render(request, 'site_cars/invoice_form.html', {
        'car': car, 'bill': bill, 'addable_cars': addable_cars,
    })


@section_required("sales")
def invoice_view(request, pk, bill_pk):
    """Render a printable invoice. Use browser print dialog for PDF export."""
    if _is_public_schema():
        return redirect('home')
    car = get_object_or_404(SiteCar, pk=pk)
    bill = get_object_or_404(SiteBill, pk=bill_pk, site_car=car)
    shipment = getattr(bill, 'shipment', None)
    return render(request, 'site_cars/invoice.html', {
        'car': car, 'bill': bill, 'shipment': shipment,
        'tenant': getattr(connection, 'tenant', None),
        'currency_name': _car_currency_name(car),
    })


@section_required("sales")
def contract_view(request, pk, bill_pk):
    """Printable per-tenant 'buyer contract' (عقد وساطة) for a bill — the blanks
    are filled from the tenant's contract settings + the bill's buyer/car."""
    if _is_public_schema():
        return redirect('home')
    car = get_object_or_404(SiteCar, pk=pk)
    bill = get_object_or_404(SiteBill, pk=bill_pk, site_car=car)
    tenant = getattr(connection, 'tenant', None)
    # Buyer identity: prefer the bill's own fields, else the linked user's profile.
    bu = bill.buyer_user
    prof = getattr(bu, 'profile', None) if bu else None
    buyer = {
        'name': bill.buyer_name or (bu.get_full_name() if bu else '') or (bu.username if bu else ''),
        'id': bill.buyer_id_number or (getattr(prof, 'identity_number', '') if prof else ''),
        'phone': bill.buyer_phone or (getattr(prof, 'phone', '') if prof else ''),
    }
    chassis = (car.external_id or '').replace('faqih_', '') or car.vin or car.registration_no or ''
    return render(request, 'site_cars/contract.html', {
        'car': car, 'bill': bill, 'tenant': tenant, 'buyer': buyer, 'chassis': chassis,
    })


# ── سند قبض (receipt vouchers) ──────────────────────────────────────────────
# Arabic amount-in-words (تفقيط) for the printed voucher.
_TFQ_ONES = ['', 'واحد', 'اثنان', 'ثلاثة', 'أربعة', 'خمسة', 'ستة', 'سبعة', 'ثمانية', 'تسعة', 'عشرة',
             'أحد عشر', 'اثنا عشر', 'ثلاثة عشر', 'أربعة عشر', 'خمسة عشر', 'ستة عشر', 'سبعة عشر',
             'ثمانية عشر', 'تسعة عشر']
_TFQ_TENS = ['', '', 'عشرون', 'ثلاثون', 'أربعون', 'خمسون', 'ستون', 'سبعون', 'ثمانون', 'تسعون']
_TFQ_HUNDREDS = ['', 'مائة', 'مائتان', 'ثلاثمائة', 'أربعمائة', 'خمسمائة', 'ستمائة', 'سبعمائة', 'ثمانمائة', 'تسعمائة']


def _tafqit_under_1000(n):
    parts = []
    h, rem = divmod(n, 100)
    if h:
        parts.append(_TFQ_HUNDREDS[h])
    if rem:
        if rem < 20:
            parts.append(_TFQ_ONES[rem])
        else:
            t, o = divmod(rem, 10)
            parts.append((_TFQ_ONES[o] + ' و' + _TFQ_TENS[t]) if o else _TFQ_TENS[t])
    return ' و'.join(parts)


def _tafqit(n):
    """Arabic words for a positive integer amount (< 1 billion)."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ''
    if n <= 0 or n >= 1_000_000_000:
        return ''
    parts = []
    millions, rem = divmod(n, 1_000_000)
    thousands, units = divmod(rem, 1000)
    if millions:
        parts.append('مليون' if millions == 1 else 'مليونان' if millions == 2
                     else _tafqit_under_1000(millions) + (' ملايين' if millions <= 10 else ' مليوناً'))
    if thousands:
        parts.append('ألف' if thousands == 1 else 'ألفان' if thousands == 2
                     else _tafqit_under_1000(thousands) + (' آلاف' if thousands <= 10 else ' ألفاً'))
    if units:
        parts.append(_tafqit_under_1000(units))
    return ' و'.join(parts)


_CURRENCY_AR = {'SAR': 'ريال', 'USD': 'دولار', 'AED': 'درهم', 'EUR': 'يورو', 'KRW': 'وون'}


def _car_currency_name(car):
    """Arabic currency name for a site car's price currency (bills/receipts
    are denominated in the car's own currency, not always SAR)."""
    return _CURRENCY_AR.get((getattr(car, 'currency', '') or 'SAR').upper(), 'ريال')


def _bill_buyer(bill):
    """Buyer identity for printable documents: the bill's own fields, else the
    linked user's profile (same resolution as the buyer contract)."""
    bu = bill.buyer_user
    prof = getattr(bu, 'profile', None) if bu else None
    return {
        'name': bill.buyer_name or (bu.get_full_name() if bu else '') or (bu.username if bu else ''),
        'id': bill.buyer_id_number or (getattr(prof, 'identity_number', '') if prof else ''),
        'phone': bill.buyer_phone or (getattr(prof, 'phone', '') if prof else ''),
    }


@section_required("sales")
def receipt_add(request, pk, bill_pk):
    """Record a payment (deposit/installment/settlement) against a bill and
    open its printable سند قبض."""
    if _is_public_schema():
        return redirect('home')
    car = get_object_or_404(SiteCar, pk=pk)
    bill = get_object_or_404(SiteBill, pk=bill_pk, site_car=car)
    if request.method == 'POST':
        from decimal import Decimal, InvalidOperation
        from django.utils.dateparse import parse_date
        try:
            amount = Decimal(str(request.POST.get('amount') or '').strip())
        except (InvalidOperation, ValueError):
            amount = Decimal('0')
        if amount > 0:
            method = request.POST.get('method')
            purpose = request.POST.get('purpose')
            r = SiteReceipt.objects.create(
                bill=bill,
                amount=amount,
                method=method if method in dict(SiteReceipt.METHOD_CHOICES) else 'transfer',
                purpose=purpose if purpose in dict(SiteReceipt.PURPOSE_CHOICES) else 'deposit',
                note=(request.POST.get('note') or '').strip()[:255],
                received_by=(request.POST.get('received_by') or '').strip()[:120],
                date=parse_date(request.POST.get('date') or '') or timezone.localdate(),
            )
            messages.success(request, f'تم إنشاء سند القبض {r.receipt_number}.')
            return redirect('receipt_view', pk=car.pk, bill_pk=bill.pk, receipt_pk=r.pk)
        messages.error(request, 'أدخل مبلغاً صحيحاً لسند القبض.')
    return redirect('invoice_view', pk=car.pk, bill_pk=bill.pk)


@section_required("sales")
def receipt_view(request, pk, bill_pk, receipt_pk):
    """Printable سند قبض for one recorded payment."""
    if _is_public_schema():
        return redirect('home')
    car = get_object_or_404(SiteCar, pk=pk)
    bill = get_object_or_404(SiteBill, pk=bill_pk, site_car=car)
    receipt = get_object_or_404(SiteReceipt, pk=receipt_pk, bill=bill)
    chassis = (car.external_id or '').replace('faqih_', '') or car.vin or car.registration_no or ''
    return render(request, 'site_cars/receipt.html', {
        'car': car, 'bill': bill, 'receipt': receipt,
        'tenant': getattr(connection, 'tenant', None),
        'buyer': _bill_buyer(bill),
        'chassis': chassis,
        'amount_words': _tafqit(receipt.amount),
        'currency_name': _car_currency_name(car),
    })


@section_required("sales")
def receipt_delete(request, pk, bill_pk, receipt_pk):
    """Remove a mistakenly-entered receipt (POST only)."""
    if _is_public_schema():
        return redirect('home')
    car = get_object_or_404(SiteCar, pk=pk)
    bill = get_object_or_404(SiteBill, pk=bill_pk, site_car=car)
    if request.method == 'POST':
        receipt = get_object_or_404(SiteReceipt, pk=receipt_pk, bill=bill)
        num = receipt.receipt_number
        receipt.delete()
        messages.success(request, f'تم حذف سند القبض {num}.')
    return redirect('invoice_view', pk=car.pk, bill_pk=bill.pk)


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


@section_required("sales")
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

@section_required("orders")
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


@section_required("orders")
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


@section_required("reviews")
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


@section_required("reviews")
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


@section_required("reviews")
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


# ──────────────────── Shareable car collections (staff) ────────────────────

def _resolve_collection_refs(refs):
    """Turn ["api:123", "site:45"] into display dicts for the builder/share page.
    Skips refs whose car no longer exists."""
    from cars.models import ApiCar
    from .models import SiteCar
    api_ids = [r.split(":", 1)[1] for r in refs if r.startswith("api:")]
    site_ids = [r.split(":", 1)[1] for r in refs if r.startswith("site:")]
    api = {str(c.id): c for c in ApiCar.objects.filter(id__in=api_ids).select_related("manufacturer", "model")}
    site = {str(c.id): c for c in SiteCar.objects.filter(id__in=site_ids)}
    out = []
    for r in refs:  # preserve the chosen order
        kind, _id = (r.split(":", 1) + [""])[:2]
        if kind == "api" and _id in api:
            c = api[_id]
            img = c.image or (c.images[0] if getattr(c, "images", None) else "")
            out.append({
                "ref": r, "kind": "api", "title": c.title,
                "year": c.year, "price": c.price, "currency": "KRW", "src_currency": "",
                "image": img, "url": reverse("car_detail", args=[c.slug]) if c.slug else "#",
            })
        elif kind == "site" and _id in site:
            c = site[_id]
            out.append({
                "ref": r, "kind": "site", "title": c.title,
                "year": c.year, "price": c.price, "currency": c.currency, "src_currency": c.currency,
                "image": (c.image.url if c.image else ""),
                "url": reverse("site_car_detail", args=[c.id]),
            })
    return out


@section_required("cars")
def share_search(request):
    """AJAX: search the full catalogue (ApiCar + SiteCar) for the share builder."""
    if _is_public_schema():
        return JsonResponse({"results": []})
    from cars.models import ApiCar
    q = (request.GET.get("q") or "").strip()
    results = []
    if q:
        api = (ApiCar.objects.filter(
                    Q(title__icontains=q) | Q(manufacturer__name__icontains=q)
                    | Q(model__name__icontains=q) | Q(lot_number__icontains=q))
               .select_related("manufacturer", "model")[:15])
        for c in api:
            img = c.image or (c.images[0] if getattr(c, "images", None) else "")
            results.append({"ref": f"api:{c.id}", "title": c.title, "year": c.year,
                            "price": c.price, "currency": "KRW", "kind": "api", "image": img})
        site = SiteCar.objects.filter(
            Q(title__icontains=q) | Q(manufacturer__icontains=q) | Q(model__icontains=q))[:15]
        for c in site:
            results.append({"ref": f"site:{c.id}", "title": c.title, "year": c.year,
                            "price": c.price, "currency": c.currency, "kind": "site",
                            "image": (c.image.url if c.image else "")})
    return JsonResponse({"results": results})


@section_required("cars")
def share_builder(request):
    """Staff page to build shareable car collections + list existing ones."""
    if _is_public_schema():
        return redirect("site_dashboard")
    from .models import SharedCollection
    collections = SharedCollection.objects.all()[:50]
    return render(request, "site_cars/share_builder.html", {
        "collections": collections,
    })


@section_required("cars")
@require_POST
def share_create(request):
    if _is_public_schema():
        return redirect("site_dashboard")
    from .models import SharedCollection
    import json as _json
    try:
        refs = _json.loads(request.POST.get("refs") or "[]")
    except ValueError:
        refs = []
    refs = [r for r in refs if isinstance(r, str) and (r.startswith("api:") or r.startswith("site:"))][:60]
    if not refs:
        messages.error(request, "اختر سيارة واحدة على الأقل.")
        return redirect("share_builder")
    sc = SharedCollection.objects.create(title=(request.POST.get("title") or "").strip(), car_refs=refs)
    messages.success(request, "تم إنشاء رابط المشاركة.")
    return redirect(f"{reverse('share_builder')}?new={sc.token}")


@section_required("cars")
@require_POST
def share_delete(request, pk):
    if _is_public_schema():
        return redirect("site_dashboard")
    from .models import SharedCollection
    SharedCollection.objects.filter(pk=pk).delete()
    messages.success(request, "تم حذف المجموعة.")
    return redirect("share_builder")


def shared_collection(request, token):
    """Public page rendering a shared car collection."""
    if _is_public_schema():
        raise Http404
    from .models import SharedCollection
    sc = get_object_or_404(SharedCollection, token=token)
    cars = _resolve_collection_refs(sc.car_refs)
    return render(request, "site_cars/shared_collection.html", {
        "collection": sc, "cars": cars,
    })


@section_required("cars")
def cart_page(request):
    """Dedicated 'share cart' page. The cart lives in the browser (localStorage,
    filled from the car list); this page renders it with each car's own link."""
    return render(request, "site_cars/cart.html", {})


def auctions_live(request):
    """Live-auctions page for a tenant whose auction backend is configured.
    Reads the external auction API (kocar.store-style) via the proxy below."""
    if _is_public_schema():
        return redirect('home')
    tenant = getattr(connection, 'tenant', None)
    base = (getattr(tenant, 'auction_api_base', '') or '').rstrip('/')
    if not base:
        raise Http404
    return render(request, 'site_cars/auctions_live.html', {'tenant': tenant, 'auction_base': base})


# Public read-only endpoints of the external auction backend we re-expose.
_AUCTION_PROXY_ALLOWED = {'auctions', 'lots', 'direct-cars', 'car-filters'}


def auction_proxy(request, resource):
    """Server-side proxy to the tenant's external auction API — avoids CORS and
    keeps the backend URL server-side. Only whitelisted, read-only resources."""
    if _is_public_schema():
        raise Http404
    tenant = getattr(connection, 'tenant', None)
    base = (getattr(tenant, 'auction_api_base', '') or '').rstrip('/')
    if not base or resource not in _AUCTION_PROXY_ALLOWED:
        raise Http404
    import requests
    from urllib.parse import urlencode
    from django.core.cache import cache
    params = {k: v for k, v in request.GET.items() if k in ('status', 'auction', 'tab', 'make', 'model', 'year')}
    ckey = f"auctionproxy:{getattr(tenant, 'schema_name', '')}:{resource}:{urlencode(sorted(params.items()))}"
    cached = cache.get(ckey)
    if cached is None:
        try:
            r = requests.get(f"{base}/api/{resource}/", params=params, timeout=10)
            cached = {'status': r.status_code, 'body': r.text}
        except Exception:
            cached = {'status': 502, 'body': '[]'}
        cache.set(ckey, cached, 20)  # short TTL: auctions move fast
    return HttpResponse(cached['body'], status=cached['status'], content_type='application/json')


@site_admin_required
def telegram_status(request):
    """Whether this dealer's Telegram is connected + the one-time connect link."""
    from tenants import telegram_bot as tg
    tenant = getattr(connection, "tenant", None)
    link = ""
    if tenant and tg.is_configured() and tg.bot_username():
        link = f"https://t.me/{tg.bot_username()}?start={tg.connect_token(tenant.id)}"
    chat_id = getattr(tenant, "telegram_chat_id", "") if tenant else ""
    who = getattr(tenant, "telegram_chat_name", "") if tenant else ""
    if chat_id and not who and tg.is_configured():
        # connected before we started recording identity — backfill once
        try:
            chat = tg.get_chat(chat_id)
            who = " ".join(p for p in [chat.get("first_name"), chat.get("last_name")] if p)
            if chat.get("username"):
                who = (who + f' (@{chat["username"]})').strip()
            if who:
                type(tenant).objects.filter(pk=tenant.pk).update(telegram_chat_name=who[:128])
        except Exception:
            who = ""
    return JsonResponse({
        "configured": tg.is_configured(),
        "connected": bool(chat_id),
        "who": who,
        "link": link,
    })


@site_admin_required
def telegram_send(request):
    """Push the share-cart cars to the dealer's connected Telegram chat."""
    if request.method != "POST":
        return JsonResponse({"error": "post"}, status=405)
    from tenants import telegram_bot as tg
    from cars.templatetags.custom_filters import sar_price, share_car_title
    from cars.models import ApiCar
    import re as _re
    tenant = getattr(connection, "tenant", None)
    chat_id = getattr(tenant, "telegram_chat_id", "") if tenant else ""
    if not tg.is_configured():
        return JsonResponse({"error": "not_configured"}, status=400)
    if not chat_id:
        return JsonResponse({"error": "not_connected"}, status=400)
    import html as _html
    import json as _json
    try:
        cars = _json.loads((request.body or b"").decode() or "{}").get("cars", [])
    except Exception:
        cars = []
    cars = [c for c in cars if (c.get("url") or "").strip()]
    # Always rebuild each title from the car record as "make model transmission
    # fuel cc" — never trust/echo the raw title captured in the browser.
    _slug_re = _re.compile(r"/cars/([^/?#]+)/?")
    _slugs = [m.group(1) for m in (_slug_re.search(c.get("url") or "") for c in cars) if m]
    _by_slug = {
        c.slug: c for c in ApiCar.objects.filter(slug__in=_slugs)
        .select_related("manufacturer", "model")
    }
    sent = 0
    for c in cars[:60]:
        url = (c.get("url") or "").strip()
        m = _slug_re.search(url)
        car = _by_slug.get(m.group(1)) if m else None
        title = _html.escape(share_car_title(car) if car else (c.get("title") or "").strip())
        img = (c.get("image") or "").strip()
        krw = c.get("priceKrw")
        price = f"{sar_price(krw):,} ﷼" if krw else (c.get("price") or "").strip()
        caption = "\n".join(p for p in [
            f"🚗 <b>{title}</b>" if title else "",
            f"💰 {price}" if price else "",
            url,
        ] if p)
        # Each car is its own photo+caption message; if Telegram can't fetch the
        # image, fall back to a text message so no car is silently dropped.
        res = tg.send_photo(chat_id, img, caption) if img else tg.send_message(chat_id, caption)
        if res and res.get("ok"):
            sent += 1
        elif img and (tg.send_message(chat_id, caption) or {}).get("ok"):
            sent += 1
    return JsonResponse({"sent": sent, "total": len(cars)})
