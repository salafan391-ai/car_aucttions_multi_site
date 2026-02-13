from datetime import datetime, date

from django.core.paginator import Paginator
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.db.models import Q
from django.shortcuts import render, get_object_or_404, redirect

from django.http import JsonResponse

from .models import ApiCar, Manufacturer, CarModel, CarRequest, Contact, CarColor, BodyType, Category


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

    manufacturers = Manufacturer.objects.all().order_by('name')
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

    year = request.GET.get('year')
    if year:
        qs = qs.filter(year=year)

    color = request.GET.get('color')
    if color:
        qs = qs.filter(color_id=color)

    body_type = request.GET.get('body_type')
    if body_type:
        qs = qs.filter(body_id=body_type)

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

    manufacturers = Manufacturer.objects.all().order_by('name')
    models_qs = CarModel.objects.all().order_by('name')
    if manufacturer:
        models_qs = models_qs.filter(manufacturer_id=manufacturer)
    years = ApiCar.objects.values_list('year', flat=True).distinct().order_by('-year')
    colors = CarColor.objects.all().order_by('name')
    body_types = BodyType.objects.all().order_by('name')
    fuels = ApiCar.objects.values_list('fuel', flat=True).exclude(fuel__isnull=True).exclude(fuel='').distinct().order_by('fuel')
    transmissions = ApiCar.objects.values_list('transmission', flat=True).exclude(transmission__isnull=True).exclude(transmission='').distinct().order_by('transmission')

    # Counts for tabs
    base_qs = _exclude_expired_auctions(ApiCar.objects.all())
    count_all = base_qs.count()
    count_cars = base_qs.exclude(category__name='auction').count()
    count_auction = base_qs.filter(category__name='auction').count()

    # Popular manufacturers (top 20 by car count)
    from django.db.models import Count
    popular_manufacturers = Manufacturer.objects.annotate(
        car_count=Count('apicar')
    ).order_by('-car_count')[:20]

    context = {
        'page_obj': page_obj,
        'manufacturers': manufacturers,
        'popular_manufacturers': popular_manufacturers,
        'models': models_qs,
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
