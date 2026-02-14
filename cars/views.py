from datetime import datetime, date

from django.core.paginator import Paginator
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.db.models import Q
from django.shortcuts import render, get_object_or_404, redirect

from django.http import JsonResponse

from .models import ApiCar, Manufacturer, CarModel, CarRequest, Contact, CarColor, BodyType, Category, CarBadge, Wishlist


def _exclude_expired_auctions(qs):
    """Exclude auction cars whose auction_date has passed."""
    now = datetime.now()
    return qs.exclude(category__name='auction', auction_date__lt=now)


def home(request):
    _base_qs = _exclude_expired_auctions(
        ApiCar.objects.select_related(
            'manufacturer', 'model', 'badge', 'color'
        )
    )
    latest_cars = _base_qs.exclude(category__name='auction').order_by('-created_at')[:12]
    latest_auctions = _base_qs.filter(category__name='auction').order_by('-created_at')[:12]
    
    # Only show manufacturers that have non-expired cars
    base_qs = _exclude_expired_auctions(ApiCar.objects.all())
    manufacturers = Manufacturer.objects.filter(
        apicar__in=base_qs
    ).distinct().order_by('name')
    
    # Only show body types that have non-expired cars
    body_types = BodyType.objects.filter(
        apicar__in=base_qs
    ).distinct().order_by('name')
    
    years = ApiCar.objects.values_list('year', flat=True).distinct().order_by('-year')

    site_cars = []
    from django.db import connection
    tenant = getattr(connection, 'tenant', None)
    if tenant and tenant.schema_name != 'public':
        from site_cars.models import SiteCar
        site_cars = SiteCar.objects.order_by('-created_at')[:8]

    context = {
        'latest_cars': latest_cars,
        'latest_auctions': latest_auctions,
        'site_cars': site_cars,
        'manufacturers': manufacturers,
        'body_types': body_types,
        'years': years,
        'total_cars': _exclude_expired_auctions(ApiCar.objects.filter(status='available')).count(),
        'auction_count': _exclude_expired_auctions(ApiCar.objects.filter(category__name='auction')).count(),
        'cars_count': _exclude_expired_auctions(ApiCar.objects.exclude(category__name='auction')).count(),
        'total_manufacturers': Manufacturer.objects.count(),
        'total_models': CarModel.objects.count(),
        'year': datetime.now().year,
    }
    return render(request, 'cars/home.html', context)


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

    year = request.GET.get('year')
    if year:
        qs = qs.filter(year=year)

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
        manufacturers = Manufacturer.objects.filter(apicar__in=base_auction_qs).distinct().order_by('name')
        models_qs = CarModel.objects.filter(apicar__in=base_auction_qs).distinct().order_by('name')
    else:
        manufacturers = Manufacturer.objects.all().order_by('name')
        models_qs = CarModel.objects.all().order_by('name')
    
    if manufacturer:
        if car_type == 'auction':
            models_qs = models_qs.filter(manufacturer_id=manufacturer, apicar__in=base_auction_qs).distinct()
        else:
            models_qs = models_qs.filter(manufacturer_id=manufacturer)
    years = ApiCar.objects.values_list('year', flat=True).distinct().order_by('-year')
    colors = CarColor.objects.all().order_by('name')
    
    # Filter body types based on car type
    if car_type == 'auction':
        body_types = BodyType.objects.filter(apicar__in=base_auction_qs).distinct().order_by('name')
    else:
        base_regular_qs = _exclude_expired_auctions(ApiCar.objects.exclude(category__name='auction'))
        body_types = BodyType.objects.filter(
            apicar__in=base_regular_qs
        ).distinct().order_by('name')
    
    fuels = ApiCar.objects.values_list('fuel', flat=True).exclude(fuel__isnull=True).exclude(fuel='').distinct().order_by('fuel')
    transmissions = ApiCar.objects.values_list('transmission', flat=True).exclude(transmission__isnull=True).exclude(transmission='').distinct().order_by('transmission')
    badges = CarBadge.objects.all().order_by('name')

    # Counts for tabs
    base_qs = _exclude_expired_auctions(ApiCar.objects.all())
    count_all = base_qs.count()
    count_cars = base_qs.exclude(category__name='auction').count()
    count_auction = base_qs.filter(category__name='auction').count()

    # Popular manufacturers (top 20 by car count)
    from django.db.models import Count
    if car_type == 'auction':
        popular_manufacturers = Manufacturer.objects.filter(apicar__in=base_auction_qs).annotate(
            car_count=Count('apicar', filter=Q(apicar__in=base_auction_qs))
        ).order_by('-car_count')[:20]
    else:
        popular_manufacturers = Manufacturer.objects.annotate(
            car_count=Count('apicar')
        ).order_by('-car_count')[:20]

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
        'query_string': query_string,
        'count_all': count_all,
        'count_cars': count_cars,
        'count_auction': count_auction,
    }
    return render(request, 'cars/car_list.html', context)


def expired_auctions(request):
    now = datetime.now()
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
    models = list(
        CarModel.objects.filter(manufacturer_id=manufacturer_id)
        .order_by('name')
        .values('id', 'name')
    )
    return JsonResponse(models, safe=False)

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

def car_detail(request, pk):
    car = get_object_or_404(
        ApiCar.objects.select_related(
            'manufacturer', 'model', 'badge', 'color', 'seat_color', 'body'
        ),
        pk=pk,
    )

    ratings = []
    user_rating = None
    avg_rating = 0
    from django.db import connection
    tenant = getattr(connection, 'tenant', None)
    if tenant and tenant.schema_name != 'public':
        from site_cars.models import SiteRating
        from django.db.models import Avg
        ratings = SiteRating.objects.filter(car=car).select_related('user')
        avg_obj = ratings.aggregate(avg=Avg('rating'))
        avg_rating = avg_obj['avg'] or 0
        if request.user.is_authenticated:
            user_rating = ratings.filter(user=request.user).first()

    context = {
        'car': car,
        'ratings': ratings,
        'avg_rating': avg_rating,
        'user_rating': user_rating,
    }
    return render(request, 'cars/car_detail.html', context)


def car_request(request):
    if request.method == 'POST':
        CarRequest.objects.create(
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
        Contact.objects.create(
            name=request.POST.get('name', ''),
            email=request.POST.get('email', ''),
            phone=request.POST.get('phone', ''),
            message=request.POST.get('message', ''),
        )
        messages.success(request, 'تم إرسال رسالتك بنجاح! شكراً لتواصلك معنا.')
        return redirect('contact')
    return render(request, 'cars/contact.html')


def toggle_wishlist(request, car_id):
    """Toggle car in user's wishlist"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'يجب تسجيل الدخول أولاً', 'redirect': '/login/?next=' + request.META.get('HTTP_REFERER', '/')}, status=401)
    
    try:
        car = get_object_or_404(ApiCar, pk=car_id)
        
        # Debug info
        print(f"User ID: {request.user.id}, Username: {request.user.username}")
        print(f"Car ID: {car_id}, Car Title: {car.title}")
        
        wishlist_item, created = Wishlist.objects.get_or_create(
            user=request.user, 
            car=car
        )
        print(f"Wishlist item created: {created}")
        
    except Exception as e:
        print(f"Error in toggle_wishlist: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': f'حدث خطأ: {str(e)}'}, status=500)
    
    if not created:
        # Item exists, so remove it
        wishlist_item.delete()
        return JsonResponse({'in_wishlist': False})
    else:
        # Item was created
        return JsonResponse({'in_wishlist': True})


@login_required
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
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        try:
            user_in_tenant = User.objects.get(id=request.user.id)
            count = Wishlist.objects.filter(user=user_in_tenant).count()
            return JsonResponse({'count': count})
        except User.DoesNotExist:
            return JsonResponse({'count': 0})
    except Exception as e:
        return JsonResponse({'count': 0})
