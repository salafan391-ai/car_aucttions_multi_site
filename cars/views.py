from datetime import datetime, date

from django.core.paginator import Paginator
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.db.models import Q, Max
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db.models import Count
from django.utils import timezone

from django.http import JsonResponse, HttpResponse
from django.core.cache import cache
from django.views.decorators.cache import cache_page, cache_control
import hashlib
from django.db import connection

from .models import ApiCar, Manufacturer, CarModel, CarRequest, Contact, CarColor, BodyType, Category, CarBadge, Wishlist, CarSeatColor, Post, PostLike, PostComment, PostImage


def _is_public_schema():
    """Check if current schema is public"""
    return connection.schema_name == 'public'


def _get_current_tenant():
    """Get current tenant or None"""
    return getattr(connection, 'tenant', None)


def _exclude_expired_auctions(qs):
    """Exclude auction cars whose auction_date has passed."""
    now = timezone.now()
    return qs.exclude(category__name='auction', auction_date__lt=now)


@ensure_csrf_cookie
def home(request):
    # Use select_related for foreign keys to reduce queries
    _base_qs = _exclude_expired_auctions(
        ApiCar.objects.select_related(
            'manufacturer', 'model', 'badge', 'color', 'body', 'category'
        )
    )
    
    # Get cars excluding auctions - limit early for performance
    latest_cars = _base_qs.exclude(category__name='auction').order_by('-created_at')[:12]
    
    # Get auctions only - limit early for performance
    latest_auctions = _base_qs.filter(category__name='auction').order_by('-created_at')[:12]
    
    # Only show manufacturers that have non-expired cars
    base_qs = _exclude_expired_auctions(ApiCar.objects.all())
    manufacturers = Manufacturer.objects.filter(
        apicar__in=base_qs
    ).annotate(car_count=Count('apicar')).distinct().order_by('-car_count')[:20]  # Limit to top 20
    
    # Only show body types that have non-expired cars
    body_types = BodyType.objects.filter(
        apicar__in=base_qs
    ).distinct().order_by('name')[:15]  # Limit to 15
    
    # Get distinct years efficiently
    years = ApiCar.objects.values_list('year', flat=True).distinct().order_by('-year')[:20]  # Last 20 years

    site_cars = []
    tenant = _get_current_tenant()
    if tenant and tenant.schema_name != 'public':
        from site_cars.models import SiteCar
        site_cars = SiteCar.objects.only('id', 'title', 'image', 'manufacturer', 'model', 'year', 'price').order_by('-created_at')[:8]

    # Get posts count and latest post (filtered by tenant)
    posts_qs = Post.objects.filter(is_published=True)
    if tenant and not _is_public_schema():
        posts_qs = posts_qs.filter(tenant=tenant)
    
    posts_count = posts_qs.count()
    latest_post = posts_qs.select_related('author').prefetch_related('images').order_by('-created_at').first()

    # Use exists() for faster boolean checks
    available_cars_qs = _exclude_expired_auctions(ApiCar.objects.filter(status='available'))
    
    context = {
        'latest_cars': latest_cars,
        'latest_auctions': latest_auctions,
        'site_cars': site_cars,
        'manufacturers': manufacturers,
        'body_types': body_types,
        'years': years,
        'total_cars': available_cars_qs.count(),
        'auction_count': _exclude_expired_auctions(ApiCar.objects.filter(category__name='auction')).count(),
        'cars_count': _exclude_expired_auctions(ApiCar.objects.exclude(category__name='auction')).count(),
        'total_manufacturers': Manufacturer.objects.count(),
        'total_models': CarModel.objects.count(),
        'posts_count': posts_count,
        'latest_post': latest_post,
        'total_models': CarModel.objects.count(),
        'posts_count': posts_count,
        'latest_post': latest_post,
        'year': datetime.now().year,
    }
    return render(request, 'cars/home.html', context)


@ensure_csrf_cookie
@cache_page(60 * 5)  # Cache for 5 minutes
def car_list(request):
    qs = _exclude_expired_auctions(
        ApiCar.objects.select_related(
            'manufacturer', 'model', 'badge', 'color', 'body'
        )
    )

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(lot_number__icontains=q) | Q(vin__icontains=q)
            | Q(manufacturer__name__icontains=q) | Q(model__name__icontains=q)
            | Q(badge__name__icontains=q)
        )

    manufacturer = request.GET.get('manufacturer')
    if manufacturer:
        qs = qs.filter(manufacturer_id=manufacturer)

    model = request.GET.get('model')
    if model:
        qs = qs.filter(model_id=model)

    badge = request.GET.get('badge')
    if badge:
        qs = qs.filter(badge_id=badge)

    year_from = request.GET.get('year_from')
    if year_from:
        try:
            qs = qs.filter(year__gte=int(year_from))
        except ValueError:
            pass

    year_to = request.GET.get('year_to')
    if year_to:
        try:
            qs = qs.filter(year__lte=int(year_to))
        except ValueError:
            pass

    color = request.GET.get('color')
    if color:
        qs = qs.filter(color_id=color)

    body_type = request.GET.get('body_type')
    if body_type:
        qs = qs.filter(body__name=body_type)

    fuel = request.GET.get('fuel')
    if fuel:
        qs = qs.filter(fuel__iexact=fuel)

    transmission = request.GET.get('transmission')
    if transmission:
        qs = qs.filter(transmission__iexact=transmission)

    seat_count = request.GET.get('seat_count')
    if seat_count:
        qs = qs.filter(seat_count=seat_count)

    seat_color = request.GET.get('seat_color')
    if seat_color:
        qs = qs.filter(seat_color_id=seat_color)

    auction_name = request.GET.get('auction_name', '').strip()
    if auction_name:
        qs = qs.filter(auction_name__iexact=auction_name)

    car_type = request.GET.get('car_type')
    if car_type == 'auction':
        qs = qs.filter(category__name='auction')
    elif car_type == 'cars':
        qs = qs.exclude(category__name='auction')

    status = request.GET.get('status')
    if status:
        qs = qs.filter(status=status)

    price_min = request.GET.get('price_min')
    if price_min:
        try:
            qs = qs.filter(price__gte=int(price_min))
        except ValueError:
            pass

    price_max = request.GET.get('price_max')
    if price_max:
        try:
            qs = qs.filter(price__lte=int(price_max))
        except ValueError:
            pass

    mileage_min = request.GET.get('mileage_min')
    if mileage_min:
        try:
            qs = qs.filter(mileage__gte=int(mileage_min))
        except ValueError:
            pass

    mileage_max = request.GET.get('mileage_max')
    if mileage_max:
        try:
            qs = qs.filter(mileage__lte=int(mileage_max))
        except ValueError:
            pass

    sort = request.GET.get('sort', '-created_at')
    allowed_sorts = ['-created_at', 'price', '-price', '-year', 'year', 'mileage', '-mileage']
    if sort in allowed_sorts:
        qs = qs.order_by(sort)
    else:
        qs = qs.order_by('-created_at')

    paginator = Paginator(qs, 24)
    page_obj = paginator.get_page(request.GET.get('page'))

    query_params = request.GET.copy()
    query_params.pop('page', None)
    query_string = query_params.urlencode()

    # Filter manufacturers and models based on car type
    car_type = request.GET.get('car_type')
    if car_type == 'auction':
        # For auctions, only show manufacturers/models for non-expired auction cars
        base_auction_qs = _exclude_expired_auctions(ApiCar.objects.filter(category__name='auction'))
        manufacturers = Manufacturer.objects.filter(apicar__in=base_auction_qs).distinct().order_by('name')[:50]
        models_qs = CarModel.objects.filter(apicar__in=base_auction_qs).distinct().order_by('name')
    else:
        manufacturers = Manufacturer.objects.all().order_by('name')[:50]
        models_qs = CarModel.objects.all().order_by('name')
    
    if manufacturer:
        if car_type == 'auction':
            models_qs = models_qs.filter(manufacturer_id=manufacturer, apicar__in=base_auction_qs).distinct()
        else:
            models_qs = models_qs.filter(manufacturer_id=manufacturer)
    
    # Apply limit after all filters
    models_qs = models_qs[:100]
    years = ApiCar.objects.values_list('year', flat=True).distinct().order_by('-year')[:30]  # Last 30 years

    # Filter body types based on car type
    if car_type == 'auction':
        body_types = BodyType.objects.filter(apicar__in=base_auction_qs).distinct().order_by('name')[:20]
    else:
        base_regular_qs = _exclude_expired_auctions(ApiCar.objects.exclude(category__name='auction'))
        body_types = BodyType.objects.filter(
            apicar__in=base_regular_qs
        ).distinct().order_by('name')[:20]
    
    # Scope filter options to the current car_type for relevant dropdowns
    filter_base_qs = base_auction_qs if car_type == 'auction' else _exclude_expired_auctions(ApiCar.objects.exclude(category__name='auction'))
    fuels = filter_base_qs.values_list('fuel', flat=True).exclude(fuel__isnull=True).exclude(fuel='').distinct().order_by('fuel')[:15]
    transmissions = filter_base_qs.values_list('transmission', flat=True).exclude(transmission__isnull=True).exclude(transmission='').distinct().order_by('transmission')[:10]
    seat_counts = filter_base_qs.values_list('seat_count', flat=True).exclude(seat_count__isnull=True).exclude(seat_count='').distinct().order_by('seat_count')
    colors = CarColor.objects.filter(apicar__in=filter_base_qs).distinct().order_by('name')[:30]
    seat_colors = CarSeatColor.objects.all().order_by('name')
    badges = CarBadge.objects.all().order_by('name')
    # Distinct auction names for auction filter
    auction_names = (
        ApiCar.objects.filter(category__name='auction')
        .exclude(auction_name__isnull=True).exclude(auction_name='')
        .values_list('auction_name', flat=True).distinct().order_by('auction_name')
    )

    # Counts for tabs
    base_qs = _exclude_expired_auctions(ApiCar.objects.all())
    count_all = base_qs.count()
    count_cars = base_qs.exclude(category__name='auction').count()
    count_auction = base_qs.filter(category__name='auction').count()

    # Popular manufacturers (top 20 by car count)

    if car_type == 'auction':
        popular_manufacturers = Manufacturer.objects.filter(apicar__in=base_auction_qs).annotate(
            car_count=Count('apicar', filter=Q(apicar__in=base_auction_qs))
        ).order_by('-car_count')
    else:
        popular_manufacturers = Manufacturer.objects.annotate(
            car_count=Count('apicar')
        ).order_by('-car_count')
    context = {
        'page_obj': page_obj,
        'manufacturers': manufacturers,
        'popular_manufacturers': popular_manufacturers,
        'models': models_qs,
        'badges': badges,
        'years': years,
        'colors': colors,
        'body_types': body_types,
        'fuels': fuels,
        'transmissions': transmissions,
        'seat_counts': seat_counts,
        'seat_colors': seat_colors,
        'auction_names': auction_names,
        'auction_name': request.GET.get('auction_name', ''),
        'query_string': query_string,
        'count_all': count_all,
        'count_cars': count_cars,
        'count_auction': count_auction,
        'selected_year_from': request.GET.get('year_from', ''),
        'selected_year_to': request.GET.get('year_to', ''),
    }
    return render(request, 'cars/car_list.html', context)


def expired_auctions(request):
    now = timezone.now()
    qs = ApiCar.objects.select_related(
        'manufacturer', 'model', 'badge', 'color', 'body'
    ).filter(category__name='auction', auction_date__lt=now)

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(lot_number__icontains=q)
            | Q(manufacturer__name__icontains=q) | Q(model__name__icontains=q)
        )

    sort = request.GET.get('sort', '-auction_date')
    allowed_sorts = ['-auction_date', 'auction_date', 'price', '-price', '-year', 'mileage']
    if sort in allowed_sorts:
        qs = qs.order_by(sort)
    else:
        qs = qs.order_by('-auction_date')

    paginator = Paginator(qs, 24)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
    }
    return render(request, 'cars/expired_auctions.html', context)


def api_models_by_manufacturer(request):
    manufacturer_id = request.GET.get('manufacturer_id')
    if not manufacturer_id:
        return JsonResponse([], safe=False)
    
    # Get manufacturer info for logo
    manufacturer_logo = None
    try:
        manufacturer = Manufacturer.objects.get(id=manufacturer_id)
        
        if manufacturer.logo:
            try:
                logo_string = str(manufacturer.logo).strip()
                
                # Check if logo is a file field (has .url attribute) or a string path
                if hasattr(manufacturer.logo, 'url'):
                    # It's a file field
                    manufacturer_logo = request.build_absolute_uri(manufacturer.logo.url)
                else:
                    # It's a string path - build URL manually
                    if logo_string.startswith('/'):
                        # Absolute path from root
                        manufacturer_logo = request.build_absolute_uri(logo_string)
                    elif logo_string.startswith('http'):
                        # Already a full URL
                        manufacturer_logo = logo_string
                    else:
                        # Relative path - assume it's in media
                        from django.conf import settings
                        if hasattr(settings, 'MEDIA_URL'):
                            manufacturer_logo = request.build_absolute_uri(settings.MEDIA_URL + logo_string)
                        else:
                            manufacturer_logo = request.build_absolute_uri('/media/' + logo_string)
                
            except Exception as logo_error:
                manufacturer_logo = None
    except Manufacturer.DoesNotExist:
        pass
    except Exception as e:
        pass
    
    try:
        models = list(
            CarModel.objects.filter(manufacturer_id=manufacturer_id)
            .annotate(car_count=Count('apicar'))
            .order_by('-car_count')
            .values('id', 'name', 'car_count')
        )
        
        # Add manufacturer logo to each model
        for model in models:
            model['manufacturer_logo'] = manufacturer_logo
        
        return JsonResponse(models, safe=False)
    except Exception as e:
        # Return empty list if there's any error
        return JsonResponse([], safe=False)

def api_badges_by_model(request):
    model_id = request.GET.get('model_id')
    if not model_id:
        return JsonResponse([], safe=False)
    badges = list(
        CarBadge.objects.filter(model_id=model_id)
        .order_by('name')
        .values('id', 'name')
    )
    return JsonResponse(badges, safe=False)

def car_detail_by_pk(request, pk):
    """Legacy numeric-ID URL — redirect permanently to the slug URL."""
    car = get_object_or_404(ApiCar, pk=pk)
    if car.slug:
        return redirect('car_detail', slug=car.slug, permanent=True)
    return redirect('car_detail', slug=str(pk), permanent=True)


def car_detail(request, slug):
    # Accept either a slug or a numeric string that was previously used as pk
    # Use select_related to fetch all related objects in one query
    car = get_object_or_404(
        ApiCar.objects.select_related(
            'manufacturer', 'model', 'badge', 'color', 'seat_color', 'body', 'category'
        ),
        slug=slug,
    )

    ratings = []
    user_rating = None
    avg_rating = 0
    pending_ratings = []
    tenant = _get_current_tenant()
    if tenant and tenant.schema_name != 'public':
        from site_cars.models import SiteRating
        from django.db.models import Avg
        
        # Show only approved ratings to regular users
        if request.user.is_staff:
            # Staff can see all ratings - get queryset without slicing first
            all_ratings = SiteRating.objects.filter(car=car).select_related('user').order_by('-created_at')
            # Get pending ratings for staff to review (before slicing)
            pending_ratings = all_ratings.filter(is_approved=False)[:20]
            # Then slice for display
            ratings = all_ratings[:50]
        else:
            # Regular users only see approved ratings
            ratings = SiteRating.objects.filter(car=car, is_approved=True).select_related('user').order_by('-created_at')[:50]
        
        # Calculate average only from approved ratings
        avg_obj = SiteRating.objects.filter(car=car, is_approved=True).aggregate(avg=Avg('rating'))
        avg_rating = avg_obj['avg'] or 0
        
        if request.user.is_authenticated:
            user_rating = SiteRating.objects.filter(car=car, user=request.user).first()
            
            
    print(car.seat_count)
    
    context = {
        'car': car,
        'ratings': ratings,
        'avg_rating': avg_rating,
        'user_rating': user_rating,
        'pending_ratings': pending_ratings,
        'inspection_legend': [
            ('P',   'وكالة'),
            ('A',   'وكالة'),
            ('Q',   'وكالة'),
            ('W',   'رش'),
            ('X',   'تغيير بدون رش'),
            ('XXP', 'مغير ومرشوش'),
            ('PP',  'رش تجميلي'),
            ('WR',  'رش'),
            ('R',   'وكالة'),
            ('WU',  'رش'),
        ],
    }
    return render(request, 'cars/car_detail.html', context)


def car_request(request):
    if request.method == 'POST':
        car_req = CarRequest.objects.create(
            name=request.POST.get('name', ''),
            phone=request.POST.get('phone', ''),
            city=request.POST.get('city', ''),
            brand=request.POST.get('brand', ''),
            model=request.POST.get('model', ''),
            year=request.POST.get('year', ''),
            colors=request.POST.get('colors', ''),
            fuel=request.POST.get('fuel', ''),
            details=request.POST.get('details', ''),
        )
        # Send email notification to admin
        try:
            tenant = _get_current_tenant()
            admin_email = tenant.email if tenant and tenant.email else None
            if admin_email:
                from site_cars.email_utils import send_tenant_email
                body = f"""
                <div dir="rtl" style="font-family:Arial,sans-serif;">
                <h2 style="color:#7c3aed;">🚗 طلب سيارة جديد</h2>
                <table style="border-collapse:collapse;width:100%;">
                  <tr><td style="padding:8px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:bold;">الاسم</td><td style="padding:8px;border:1px solid #e5e7eb;">{car_req.name}</td></tr>
                  <tr><td style="padding:8px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:bold;">الجوال</td><td style="padding:8px;border:1px solid #e5e7eb;">{car_req.phone}</td></tr>
                  <tr><td style="padding:8px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:bold;">المدينة</td><td style="padding:8px;border:1px solid #e5e7eb;">{car_req.city}</td></tr>
                  <tr><td style="padding:8px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:bold;">الشركة</td><td style="padding:8px;border:1px solid #e5e7eb;">{car_req.brand}</td></tr>
                  <tr><td style="padding:8px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:bold;">الموديل</td><td style="padding:8px;border:1px solid #e5e7eb;">{car_req.model}</td></tr>
                  <tr><td style="padding:8px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:bold;">السنة</td><td style="padding:8px;border:1px solid #e5e7eb;">{car_req.year}</td></tr>
                  <tr><td style="padding:8px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:bold;">الوقود</td><td style="padding:8px;border:1px solid #e5e7eb;">{car_req.fuel}</td></tr>
                  <tr><td style="padding:8px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:bold;">الألوان</td><td style="padding:8px;border:1px solid #e5e7eb;">{car_req.colors}</td></tr>
                  <tr><td style="padding:8px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:bold;">التفاصيل</td><td style="padding:8px;border:1px solid #e5e7eb;">{car_req.details or '—'}</td></tr>
                </table>
                <p style="margin-top:16px;color:#6b7280;font-size:13px;">تم الاستلام في: {car_req.created_at.strftime('%Y-%m-%d %H:%M')}</p>
                </div>
                """
                send_tenant_email(
                    recipient_email=admin_email,
                    subject=f'طلب سيارة جديد من {car_req.name}',
                    body_html=body,
                    email_type='order_notification',
                )
        except Exception:
            pass  # Never block the user if email fails
        messages.success(request, 'تم إرسال طلبك بنجاح! سنتواصل معك قريباً.')
        return redirect('car_request')
    return render(request, 'cars/car_request.html')


def register_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.first_name = request.POST.get('first_name', '')
            user.last_name = request.POST.get('last_name', '')
            user.email = request.POST.get('email', '')
            user.save()
            auth_login(request, user)
            messages.success(request, 'تم إنشاء حسابك بنجاح! مرحباً بك.')
            return redirect('home')
    else:
        form = UserCreationForm()
    return render(request, 'cars/register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            auth_login(request, user)
            messages.success(request, f'مرحباً {user.get_short_name() or user.username}!')
            next_url = request.GET.get('next', 'home')
            return redirect(next_url)
    else:
        form = AuthenticationForm()
    return render(request, 'cars/login.html', {'form': form})


def logout_view(request):
    auth_logout(request)
    messages.success(request, 'تم تسجيل الخروج بنجاح.')
    return redirect('home')


def contact(request):
    if request.method == 'POST':
        msg = Contact.objects.create(
            name=request.POST.get('name', ''),
            email=request.POST.get('email', ''),
            phone=request.POST.get('phone', ''),
            message=request.POST.get('message', ''),
        )
        # Send email notification to admin
        try:
            tenant = _get_current_tenant()
            admin_email = tenant.email if tenant and tenant.email else None
            if admin_email:
                from site_cars.email_utils import send_tenant_email
                body = f"""
                <div dir="rtl" style="font-family:Arial,sans-serif;">
                <h2 style="color:#2563eb;">✉️ رسالة تواصل جديدة</h2>
                <table style="border-collapse:collapse;width:100%;">
                  <tr><td style="padding:8px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:bold;">الاسم</td><td style="padding:8px;border:1px solid #e5e7eb;">{msg.name}</td></tr>
                  <tr><td style="padding:8px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:bold;">البريد الإلكتروني</td><td style="padding:8px;border:1px solid #e5e7eb;">{msg.email}</td></tr>
                  <tr><td style="padding:8px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:bold;">الجوال</td><td style="padding:8px;border:1px solid #e5e7eb;">{msg.phone}</td></tr>
                  <tr><td style="padding:8px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:bold;">الرسالة</td><td style="padding:8px;border:1px solid #e5e7eb;">{msg.message}</td></tr>
                </table>
                <p style="margin-top:16px;color:#6b7280;font-size:13px;">تم الاستلام في: {msg.created_at.strftime('%Y-%m-%d %H:%M')}</p>
                </div>
                """
                send_tenant_email(
                    recipient_email=admin_email,
                    subject=f'رسالة تواصل جديدة من {msg.name}',
                    body_html=body,
                    email_type='contact_notification',
                )
        except Exception:
            pass  # Never block the user if email fails
        messages.success(request, 'تم إرسال رسالتك بنجاح! شكراً لتواصلك معنا.')
        return redirect('contact')
    return render(request, 'cars/contact.html')


def toggle_wishlist(request, car_id):
    """Toggle car in user's wishlist"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'يجب تسجيل الدخول أولاً', 'redirect': '/login/?next=' + request.META.get('HTTP_REFERER', '/')}, status=401)
    
    try:
        car = get_object_or_404(ApiCar, pk=car_id)
        
        wishlist_item, created = Wishlist.objects.get_or_create(
            user=request.user, 
            car=car
        )
        
        if not created:
            # Item exists, so remove it
            wishlist_item.delete()
            in_wishlist = False
        else:
            # Item was created
            in_wishlist = True
        
        return JsonResponse({'in_wishlist': in_wishlist})
        
    except Exception as e:
        print(f"Error in toggle_wishlist: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': f'حدث خطأ: {str(e)}'}, status=500)


@login_required
@ensure_csrf_cookie
def wishlist(request):
    """Show user's wishlist"""
    wishlist_items = Wishlist.objects.filter(
        user=request.user
    ).select_related('car', 'car__manufacturer', 'car__model').order_by('-created_at')
    
    # Filter out expired auctions
    valid_items = []
    for item in wishlist_items:
        if _exclude_expired_auctions(ApiCar.objects.filter(pk=item.car.pk)).exists():
            valid_items.append(item)
        else:
            # Remove expired items from wishlist
            item.delete()
    
    paginator = Paginator(valid_items, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'wishlist_items': page_obj,
        'wishlist_count': len(valid_items),
    }
    return render(request, 'cars/wishlist.html', context)


def wishlist_count(request):
    """Get user's wishlist count"""
    if not request.user.is_authenticated:
        return JsonResponse({'count': 0})
    
    try:
        # Simple, fast count query
        count = Wishlist.objects.filter(user_id=request.user.id).count()
        return JsonResponse({'count': count})
    except Exception:
        return JsonResponse({'count': 0})
    except Exception as e:
        return JsonResponse({'count': 0})


# Posts Views
@ensure_csrf_cookie
def post_list(request):
    # Get current tenant
    tenant = _get_current_tenant()

    # Always filter by tenant — posts are site-specific
    posts = Post.objects.filter(is_published=True)
    if tenant:
        posts = posts.filter(tenant=tenant)

    posts = posts.prefetch_related('images')
    
    # Pagination
    paginator = Paginator(posts, 9)  # 9 posts per page
    page = request.GET.get('page')
    posts = paginator.get_page(page)
    
    context = {
        'posts': posts,
    }
    return render(request, 'cars/posts/post_list.html', context)


@ensure_csrf_cookie
def post_detail(request, pk):
    # Get current tenant
    tenant = _get_current_tenant()
    
    # Base query
    qs = Post.objects.prefetch_related('images').filter(pk=pk, is_published=True)

    # Always filter by tenant — posts are site-specific
    if tenant:
        qs = qs.filter(tenant=tenant)

    post = get_object_or_404(qs)
    
    # Increment view count
    post.views_count += 1
    post.save(update_fields=['views_count'])
    
    # Get comments
    comments = PostComment.objects.filter(
        post=post,
        is_approved=True
    ).select_related('user').order_by('-created_at')
    
    # Check if user has liked
    user_has_liked = False
    if request.user.is_authenticated:
        user_has_liked = PostLike.objects.filter(post=post, user=request.user).exists()
    
    context = {
        'post': post,
        'comments': comments,
        'user_has_liked': user_has_liked,
    }
    return render(request, 'cars/posts/post_detail.html', context)


@login_required
def post_like_toggle(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    # Get current tenant
    tenant = _get_current_tenant()
    
    # Base query — post_like_toggle
    qs = Post.objects.filter(pk=pk)

    # Always filter by tenant — posts are site-specific
    if tenant:
        qs = qs.filter(tenant=tenant)

    post = get_object_or_404(qs)

    like, created = PostLike.objects.get_or_create(post=post, user=request.user)
    
    if not created:
        # Unlike
        like.delete()
        return JsonResponse({
            'liked': False,
            'likes_count': post.likes_count
        })
    else:
        # Like
        return JsonResponse({
            'liked': True,
            'likes_count': post.likes_count
        })


@login_required
def post_comment_add(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    # Get current tenant
    tenant = _get_current_tenant()
    
    # Base query — post_comment_add
    qs = Post.objects.filter(pk=pk)

    # Always filter by tenant — posts are site-specific
    if tenant:
        qs = qs.filter(tenant=tenant)

    post = get_object_or_404(qs)
    comment_text = request.POST.get('comment', '').strip()
    
    if not comment_text:
        return JsonResponse({'error': 'التعليق فارغ'}, status=400)
    
    comment = PostComment.objects.create(
        post=post,
        user=request.user,
        comment=comment_text
    )
    
    return JsonResponse({
        'success': True,
        'comment': {
            'id': comment.id,
            'user': comment.user.username,
            'comment': comment.comment,
            'created_at': comment.created_at.strftime('%Y-%m-%d %H:%M'),
            'is_approved': comment.is_approved
        }
    })


@login_required
def post_comment_delete(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    comment = get_object_or_404(PostComment, pk=pk)
    
    # Only allow the comment owner to delete
    if comment.user != request.user:
        return JsonResponse({'error': 'غير مصرح'}, status=403)
    
    comment.delete()
    
    return JsonResponse({'success': True})


@login_required
def post_create(request):
    """Create a new post (staff only)"""
    if not request.user.is_staff:
        messages.error(request, 'غير مصرح لك بإنشاء منشورات')
        return redirect('post_list')
    
    # Get current tenant
    tenant = _get_current_tenant()
    
    if request.method == 'POST':
        title_ar = request.POST.get('title_ar')
        content_ar = request.POST.get('content_ar')
        video_url = request.POST.get('video_url')
        is_published = request.POST.get('is_published') == 'on'
        
        # Create post (use Arabic content for both fields)
        post = Post.objects.create(
            title=title_ar,  # Use Arabic title for English field too
            title_ar=title_ar,
            content=content_ar,  # Use Arabic content for English field too
            content_ar=content_ar,
            video_url=video_url if video_url else None,
            author=request.user,
            tenant=tenant,  # Auto-set tenant
            is_published=is_published
        )
        
        # Handle images
        images = request.FILES.getlist('images')
        for idx, image in enumerate(images):
            PostImage.objects.create(
                post=post,
                image=image,
                order=idx
            )
        
        messages.success(request, 'تم إنشاء المنشور بنجاح!')
        return redirect('post_detail', pk=post.pk)
    
    return render(request, 'cars/posts/post_form.html', {
        'action': 'create'
    })


@login_required
def post_edit(request, pk):
    """Edit an existing post (staff only)"""
    # Get current tenant
    tenant = _get_current_tenant()
    
    # Base query — post_edit
    qs = Post.objects.filter(pk=pk)

    # Always filter by tenant — posts are site-specific
    if tenant:
        qs = qs.filter(tenant=tenant)

    post = get_object_or_404(qs)
    
    if not request.user.is_staff:
        messages.error(request, 'غير مصرح لك بتعديل المنشورات')
        return redirect('post_detail', pk=pk)
    
    if request.method == 'POST':
        title_ar = request.POST.get('title_ar')
        content_ar = request.POST.get('content_ar')
        
        # Update post (use Arabic content for both fields)
        post.title = title_ar
        post.title_ar = title_ar
        post.content = content_ar
        post.content_ar = content_ar
        video_url = request.POST.get('video_url')
        post.video_url = video_url if video_url else None
        post.is_published = request.POST.get('is_published') == 'on'
        post.save()
        
        # Handle new images
        images = request.FILES.getlist('images')
        if images:
            # Get current max order
            max_order = post.images.aggregate(Max('order'))['order__max'] or 0
            for idx, image in enumerate(images):
                PostImage.objects.create(
                    post=post,
                    image=image,
                    order=max_order + idx + 1
                )
        
        messages.success(request, 'تم تحديث المنشور بنجاح!')
        return redirect('post_detail', pk=post.pk)
    
    return render(request, 'cars/posts/post_form.html', {
        'post': post,
        'action': 'edit'
    })


@login_required
def post_image_delete(request, pk):
    """Delete a post image (AJAX)"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    # Get current tenant
    tenant = _get_current_tenant()
    
    # Get image and filter by tenant through post
    image = get_object_or_404(PostImage, pk=pk)
    
    # Check tenant access
    if tenant and not _is_public_schema():
        if image.post.tenant != tenant:
            return JsonResponse({'error': 'غير مصرح'}, status=403)
    
    # Only allow staff to delete
    if not request.user.is_staff:
        return JsonResponse({'error': 'غير مصرح'}, status=403)
    
    image.delete()
    
    return JsonResponse({'success': True})


@cache_control(max_age=3600, public=True)  # Cache for 1 hour
def manufacturer_logo(request, manufacturer_id):
    """Serve manufacturer logo with caching"""
    try:
        manufacturer = Manufacturer.objects.get(id=manufacturer_id)
        if not manufacturer.logo:
            return HttpResponse('', status=404)
        
        logo_content = manufacturer.logo
        
        # If logo is a URL, redirect to it
        if logo_content.startswith('http'):
            return redirect(logo_content)
        
        # If logo contains SVG content, serve it directly
        elif '<svg' in logo_content.lower():
            return HttpResponse(logo_content, content_type='image/svg+xml')
        
        # If logo is base64 encoded, decode and serve
        elif logo_content.startswith('data:image/svg+xml;base64,'):
            import base64
            try:
                decoded_logo = base64.b64decode(logo_content.split(',')[1])
                return HttpResponse(decoded_logo, content_type='image/svg+xml')
            except:
                # Fallback to original approach if decoding fails
                pass
        
        # Fallback: serve as-is with appropriate content type
        return HttpResponse(logo_content, content_type='image/svg+xml')
        
    except Manufacturer.DoesNotExist:
        return HttpResponse('', status=404)
    except Exception as e:
        # Log error but don't break the page
        print(f"Error serving logo for manufacturer {manufacturer_id}: {str(e)}")
        return HttpResponse('', status=404)
