from datetime import datetime, date
import hashlib
import json
import logging
from urllib.parse import urlencode
import urllib.request

logger = logging.getLogger(__name__)

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
from django.views.decorators.cache import cache_control
from django.db import connection

from .models import ApiCar, Manufacturer, CarModel, CarRequest, Contact, CarColor, BodyType, Category, CarBadge, Wishlist, CarSeatColor, Post, PostLike, PostComment, PostImage
from .utils import car_models_dict
from .export_service import start_export, process_webhook_payload


# ── Manufacturer "appeal" tiers ─────────────────────────────────────────────
# Used to order the homepage rails and the default car-list ordering so the
# most desirable brands lead. Names are matched case-insensitively against
# Manufacturer.name (which is normalized to lowercase by the model's save()).
APPEAL_TIER_PREMIUM = [
    "bentley", "rolls-royce", "rolls royce", "ferrari", "lamborghini",
    "maserati", "mclaren", "aston martin", "porsche",
]
APPEAL_TIER_LUXURY = [
    "mercedes-benz", "mercedes", "bmw", "audi", "lexus", "land rover",
    "range rover", "genesis", "cadillac", "infiniti", "acura", "volvo",
    "jaguar", "tesla", "lincoln", "alpine",
]
APPEAL_TIER_MAINSTREAM = [
    "toyota", "honda", "hyundai", "kia", "nissan", "mazda", "ford",
    "chevrolet", "gmc", "volkswagen", "vw", "subaru", "mitsubishi",
    "renault", "peugeot", "citroen", "fiat", "skoda", "seat",
]


def _order_by_appeal(qs, *secondary):
    """
    Annotate `_appeal_tier` on the queryset (0=premium, 1=luxury, 2=mainstream,
    3=other) and order by it, then by the given secondary fields.

    Example: `_order_by_appeal(qs, '-created_at')`
    """
    from django.db.models import Case, When, Value, IntegerField

    qs = qs.annotate(
        _appeal_tier=Case(
            When(manufacturer__name__in=APPEAL_TIER_PREMIUM, then=Value(0)),
            When(manufacturer__name__in=APPEAL_TIER_LUXURY, then=Value(1)),
            When(manufacturer__name__in=APPEAL_TIER_MAINSTREAM, then=Value(2)),
            default=Value(3),
            output_field=IntegerField(),
        )
    )
    return qs.order_by('_appeal_tier', *secondary)


def _build_webhook_url(request):
    """
    Return the absolute webhook URL for the CURRENT tenant.

    Priority:
      1. settings.WEBHOOK_BASE_URL  (global override, e.g. for local tunnels)
      2. The tenant's primary domain from the DB  ← correct for multi-tenant
      3. request.build_absolute_uri fallback

    Using the tenant's own domain means django-tenants will automatically
    activate the right schema when ofleet calls the webhook back.
    """
    from django.conf import settings as _s

    # 1. Global override (useful for ngrok / local dev tunnels)
    base = getattr(_s, 'WEBHOOK_BASE_URL', '').rstrip('/')
    if base:
        return f"{base}/webhook/ofleet/"

    # 2. Tenant's primary domain (works correctly for every tenant in production)
    try:
        tenant = getattr(connection, 'tenant', None)
        if tenant:
            domain_obj = tenant.get_primary_domain()
            if domain_obj:
                scheme = 'https'
                return f"{scheme}://{domain_obj.domain}/webhook/ofleet/"
    except Exception:
        pass

    # 3. Fallback to request host
    return request.build_absolute_uri('/webhook/ofleet/')


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


@cache_control(public=True, max_age=600)
def landing(request):
    """Opening page – logo + CTA cards. Redirects to home if landing_is_active is False."""
    # Site-builder override: if a tenant has published a Page(kind='home'), render that.
    from site_builder.views import render_home_if_configured
    sb_response = render_home_if_configured(request)
    if sb_response is not None:
        return sb_response

    # Skip landing page if disabled for this tenant
    if not getattr(connection.tenant, 'landing_is_active', True):
        return redirect('home')

    schema = getattr(connection, 'schema_name', 'public')

    now = timezone.now()
    agg = ApiCar.objects.exclude(
        category__name='auction', auction_date__lt=now
    ).aggregate(
        cars_count=Count('id', filter=~Q(category__name='auction')),
        auction_count=Count('id', filter=Q(category__name='auction')),
    )

    next_auction = (
        ApiCar.objects.filter(
            category__name='auction',
            status='available',
            auction_date__gte=now,
        )
        .order_by('auction_date')
        .values_list('auction_date', flat=True)
        .first()
    )

    WEEKDAYS_AR = {
        0: 'الاثنين',
        1: 'الثلاثاء',
        2: 'الأربعاء',
        3: 'الخميس',
        4: 'الجمعة',
        5: 'السبت',
        6: 'الأحد',
    }
    WEEKDAYS_EN = {
        0: 'Monday',
        1: 'Tuesday',
        2: 'Wednesday',
        3: 'Thursday',
        4: 'Friday',
        5: 'Saturday',
        6: 'Sunday',
    }
    next_auction_day_ar = WEEKDAYS_AR[next_auction.weekday()] if next_auction else None
    next_auction_day_en = WEEKDAYS_EN[next_auction.weekday()] if next_auction else None

    # Get site cars + damaged cars counts
    try:
        from site_cars.models import SiteCar
        site_cars_count = (SiteCar.objects
                           .exclude(external_id__startswith='hc_')
                           .filter(status='available').count())
        damaged_cars_count = (SiteCar.objects
                              .filter(external_id__startswith='hc_').count())
    except Exception:
        site_cars_count = 0
        damaged_cars_count = 0

    # Resolve landing design template for this tenant
    _design_map = {
        'cosmos':  'cars/landing.html',
        'minimal': 'cars/landing_minimal.html',
        'bold':    'cars/landing_bold.html',
        'luxury':  'cars/landing_luxury.html',
        'neon':    'cars/landing_neon.html',
        'desert':  'cars/landing_desert.html',
        'split':     'cars/landing_split.html',
        'dashboard': 'cars/landing_dashboard.html',
        'cockpit':   'cars/landing_cockpit.html',
    }
    landing_design = getattr(connection.tenant, 'landing_design', 'cosmos') or 'cosmos'
    landing_template = _design_map.get(landing_design, 'cars/landing.html')

    # Cache key includes site_cars + damaged presence and design so each variant caches separately
    html_cache_key = (
        f"landing_html:{schema}:{landing_design}"
        f":sc{1 if site_cars_count else 0}"
        f":dc{1 if damaged_cars_count else 0}"
    )
    cached_html = cache.get(html_cache_key)
    if cached_html:
        return HttpResponse(cached_html, content_type='text/html; charset=utf-8')

    context = {
        'cars_count': agg['cars_count'],
        'auction_count': agg['auction_count'],
        'next_auction_date': next_auction,
        'next_auction_day_ar': next_auction_day_ar,
        'next_auction_day_en': next_auction_day_en,
        'site_cars_count': site_cars_count,
        'damaged_cars_count': damaged_cars_count,
        'auction_names': list(
            ApiCar.objects.filter(
                category__name='auction',
                status='available',
                auction_date__gte=now,
                auction_name__isnull=False,
            )
            .exclude(auction_name='')
            .values_list('auction_name', flat=True)
            .distinct()[:5]
        ),
    }

    response = render(request, landing_template, context)
    cache.set(html_cache_key, response.content, 60 * 30)  # 30 min
    return response


@cache_control(public=True, max_age=180)
def home(request):
    # Site-builder override: if a tenant has published a Page(kind='home'), render that.
    from site_builder.views import render_home_if_configured
    sb_response = render_home_if_configured(request)
    if sb_response is not None:
        return sb_response

    now = timezone.now()
    schema = getattr(connection, 'schema_name', 'public')

    # Cache the full rendered HTML — anonymous visitors only. The rendered HTML
    # embeds auth-specific bits (nav links, account menu, username initial), so
    # sharing it across sessions would leak state between users.
    is_anon = not request.user.is_authenticated
    html_cache_key = f"home_html_v9:{schema}"
    if is_anon:
        cached_html = cache.get(html_cache_key)
        if cached_html:
            return HttpResponse(cached_html, content_type='text/html; charset=utf-8')

    # Cache the expensive DB context by tenant schema.
    ctx_cache_key = f"home_ctx_v9:{schema}"
    context = cache.get(ctx_cache_key)

    if context is None:
        # ── Single base queryset with direct filter (no subquery) ──
        _base_qs = ApiCar.objects.select_related(
            'manufacturer', 'model', 'badge', 'category'
        ).exclude(category__name='auction', auction_date__lt=now)

        # Latest cars (non-auction) – limited early. Ordered by manufacturer
        # appeal (premium → luxury → mainstream → other), then newest first.
        latest_cars = list(
            _order_by_appeal(
                _base_qs.exclude(category__name='auction'),
                '-created_at',
            )
            .only(
                'id', 'title', 'slug', 'image', 'images', 'price', 'year',
                'mileage', 'status', 'transmission', 'address', 'created_at',
                'manufacturer__id', 'manufacturer__name', 'manufacturer__name_ar',
                'model__id', 'model__name', 'model__name_ar',
                'badge__id', 'badge__name',
                'category__id', 'category__name',
            )[:12]
        )

        # Latest auctions – limited early. Same appeal-tier ordering.
        latest_auctions = list(
            _order_by_appeal(
                _base_qs.filter(category__name='auction'),
                '-created_at',
            )
            .only(
                'id', 'title', 'slug', 'image', 'images', 'price', 'year',
                'mileage', 'status', 'transmission', 'auction_date',
                'auction_name', 'address', 'created_at',
                'manufacturer__id', 'manufacturer__name', 'manufacturer__name_ar',
                'model__id', 'model__name', 'model__name_ar',
                'badge__id', 'badge__name',
                'category__id', 'category__name',
            )[:12]
        )

        # ── Fast aggregation: use DB-side COUNT/DISTINCT instead of full table scan ──
        from django.db.models import Count as _Count
        _base_filter = ApiCar.objects.exclude(
            category__name='auction', auction_date__lt=now
        )

        _agg = _base_filter.aggregate(
            total=_Count('id'),
            auction_count=_Count('id', filter=Q(category__name='auction')),
        )
        _total         = _agg['total']
        _auction_count = _agg['auction_count']
        _cars_count    = _total - _auction_count

        _mfr_ids_set  = set(_base_filter.values_list('manufacturer_id', flat=True).distinct())
        _body_ids_set = set(_base_filter.values_list('body_id',         flat=True).distinct())
        _years_set    = list(
            _base_filter.order_by('-year')
            .values_list('year', flat=True)
            .distinct()[:20]
        )

        agg = {
            'total': _total,
            'auction_count': _auction_count,
            'cars_count': _cars_count,
            'total_manufacturers': len(_mfr_ids_set),
            'total_models': _base_filter.values('model_id').distinct().count(),
        }

        # Per-tab counts let the home mega-filter hide manufacturers without
        # listings for the active tab (Cars vs Auctions).
        manufacturers = list(
            Manufacturer.objects.filter(id__in=_mfr_ids_set)
            .annotate(
                car_count=Count('apicar'),
                cars_count=Count('apicar', filter=~Q(apicar__category__name='auction')),
                auction_count=Count('apicar', filter=Q(apicar__category__name='auction') & ~Q(apicar__auction_date__lt=now)),
            )
            .order_by('-car_count')[:20]
        )

        body_types = list(
            BodyType.objects.filter(id__in=_body_ids_set).order_by('name')[:15]
        )

        years = _years_set

        # Tenant site cars — keep damaged (external_id starts with `hc_`)
        # out of the "Our Cars" rail and surface them in their own section.
        site_cars = []
        damaged_cars = []
        site_cars_count = 0
        damaged_cars_count = 0
        tenant = _get_current_tenant()
        if tenant and tenant.schema_name != 'public':
            from site_cars.models import SiteCar
            _site_only = (
                'id', 'title', 'image', 'external_image_url',
                'manufacturer', 'model', 'year', 'price', 'status',
                'is_featured', 'mileage', 'transmission', 'external_id',
            )
            _own_qs = SiteCar.objects.exclude(external_id__startswith='hc_')
            _damaged_qs = SiteCar.objects.filter(external_id__startswith='hc_')
            site_cars = list(
                _own_qs.only(*_site_only).prefetch_related('gallery').order_by('-created_at')[:8]
            )
            damaged_cars = list(
                _damaged_qs.only(*_site_only).prefetch_related('gallery').order_by('-created_at')[:8]
            )
            site_cars_count = _own_qs.count()
            damaged_cars_count = _damaged_qs.count()

        # Posts (filtered by tenant)
        posts_qs = Post.objects.filter(is_published=True)
        if tenant and not _is_public_schema():
            posts_qs = posts_qs.filter(tenant=tenant)
        posts_count = posts_qs.count()
        latest_post = (
            posts_qs.select_related('author')
            .prefetch_related('images')
            .order_by('-created_at')
            .first()
        )

        # Order home sections by most-recently-added entry, descending.
        _section_recency = [
            ('site_cars',      site_cars[0].created_at      if site_cars      else None),
            ('damaged_cars',   damaged_cars[0].created_at   if damaged_cars   else None),
            ('latest_cars',    latest_cars[0].created_at    if latest_cars    else None),
            ('latest_auctions', latest_auctions[0].created_at if latest_auctions else None),
        ]
        home_sections_order = [
            key for key, _ in sorted(
                (s for s in _section_recency if s[1] is not None),
                key=lambda s: s[1], reverse=True,
            )
        ]

        context = {
            'latest_cars': latest_cars,
            'latest_auctions': latest_auctions,
            'site_cars': site_cars,
            'damaged_cars': damaged_cars,
            'home_sections_order': home_sections_order,
            'site_cars_count': site_cars_count,
            'damaged_cars_count': damaged_cars_count,
            'manufacturers': manufacturers,
            'body_types': body_types,
            'years': years,
            'total_cars': agg['total'],
            'auction_count': agg['auction_count'],
            'cars_count': agg['cars_count'],
            'total_manufacturers': agg['total_manufacturers'],
            'total_models': agg['total_models'],
            'posts_count': posts_count,
            'latest_post': latest_post,
            'year': datetime.now().year,
        }
        cache.set(ctx_cache_key, context, 60 * 15)  # 15 minutes

    response = render(request, 'cars/home.html', context)
    if is_anon:
        cache.set(html_cache_key, response.content, 60 * 30)  # 30 minutes
    return response


def export_auction_pdf(request):
    """
    Staff-only — triggered from the frontend car list PDF button.
    Submits the job to ofleet (which calls our webhook when done), then redirects immediately.
    The finished PDF appears in the panel / admin under «تصديرات PDF».
    """
    if not request.user.is_staff:
        return HttpResponse("غير مصرح.", status=403)

    auction_name = request.GET.get('auction_name', '').strip()
    if not auction_name:
        messages.error(request, "يرجى تحديد اسم المزاد.")
        return redirect(request.META.get('HTTP_REFERER', '/cars/'))

    entries = list(
        ApiCar.objects.filter(auction_name=auction_name)
        .exclude(entry__isnull=True).exclude(entry='')
        .values_list('entry', flat=True)
    )
    if not entries:
        messages.error(request, f"لا توجد سيارات بقيم entry في المزاد «{auction_name}».")
        return redirect(request.META.get('HTTP_REFERER', '/cars/'))

    from .models import PdfExport
    schema = getattr(connection, 'schema_name', '')

    # Build the absolute webhook URL so ofleet can call us back
    webhook_url = _build_webhook_url(request)

    try:
        _token, _job_id = start_export(entries, auction_name, webhook_url)
    except ValueError as e:
        messages.error(request, f"خطأ في الإعدادات: {e}")
        return redirect(request.META.get('HTTP_REFERER', '/cars/'))
    except Exception as e:
        messages.error(request, f"فشل بدء التصدير: {e}")
        return redirect(request.META.get('HTTP_REFERER', '/cars/'))

    PdfExport.objects.create(
        auction_name=auction_name,
        schema_name=schema,
        entry_count=len(entries),
        status=PdfExport.STATUS_PENDING,
    )

    messages.success(
        request,
        f"تم إرسال طلب تصدير PDF للمزاد «{auction_name}». "
        f"ستجد الملف جاهزاً في لوحة التحكم تحت «تصديرات PDF» خلال لحظات."
    )
    return redirect(request.META.get('HTTP_REFERER', '/cars/?car_type=auction'))


def pdf_export_panel(request):
    """
    Dedicated staff-only panel for managing PDF exports.

    GET  (no ?auction)   — landing: list of exports + auction picker.
    GET  (?auction=name) — car picker: shows all cars in that auction for selection.
    POST (action=export) — launches export for the checked car entries only.
    """
    from .models import PdfExport

    if not request.user.is_staff:
        return HttpResponse("غير مصرح.", status=403)

    schema = getattr(connection, 'schema_name', '')

    # ── POST: launch export for selected entries ─────────────────────────
    if request.method == 'POST':
        auction_name = request.POST.get('auction_name', '').strip()
        selected_ids = request.POST.getlist('car_ids')  # list of ApiCar PKs

        if not auction_name:
            messages.error(request, "اسم المزاد مفقود.")
            return redirect('pdf_export_panel')

        if not selected_ids:
            messages.error(request, "لم تحدد أي سيارة.")
            return redirect(f"{request.path}?auction={auction_name}")

        # Fetch entries only for the checked cars
        entries = list(
            ApiCar.objects.filter(pk__in=selected_ids, auction_name=auction_name)
            .exclude(entry__isnull=True).exclude(entry='')
            .values_list('entry', flat=True)
        )
        if not entries:
            messages.error(request, "السيارات المحددة لا تحتوي على قيم entry صالحة.")
            return redirect(f"{request.path}?auction={auction_name}")

        # Build the absolute webhook URL so ofleet can call us back
        webhook_url = _build_webhook_url(request)

        try:
            _token, _job_id = start_export(entries, auction_name, webhook_url)
        except ValueError as e:
            messages.error(request, f"خطأ في الإعدادات: {e}")
            return redirect(f"{request.path}?auction={auction_name}")
        except Exception as e:
            messages.error(request, f"فشل بدء التصدير: {e}")
            return redirect(f"{request.path}?auction={auction_name}")

        PdfExport.objects.create(
            auction_name=auction_name,
            schema_name=schema,
            entry_count=len(entries),
            status=PdfExport.STATUS_PENDING,
        )

        messages.success(
            request,
            f"✅ تم إرسال طلب التصدير للمزاد «{auction_name}» "
            f"({len(entries)} سيارة من أصل {len(selected_ids)} محددة). "
            f"الملف سيظهر جاهزاً خلال لحظات."
        )
        return redirect('pdf_export_panel')

    # ── GET ?auction=name → car picker step ──────────────────────────────
    auction_name = request.GET.get('auction', '').strip()
    if auction_name:
        # Base queryset for this auction (2021+)
        base_qs = (
            ApiCar.objects
            .filter(auction_name=auction_name, year__gte=2021)
            .select_related('manufacturer', 'model')
        )

        # --- Build filter option lists (from the full unfiltered base) ---
        filter_makes = (
            base_qs.order_by('manufacturer__name')
            .values_list('manufacturer__name', flat=True)
            .distinct()
        )
        filter_years = (
            base_qs.order_by('year')
            .values_list('year', flat=True)
            .distinct()
        )
        filter_fuels = (
            base_qs
            .exclude(fuel__isnull=True).exclude(fuel='')
            .order_by('fuel')
            .values_list('fuel', flat=True)
            .distinct()
        )

        # Build make→models map for JS-driven model dropdown
        # { "Toyota": ["Camry", "Corolla", ...], ... }
        make_models_qs = (
            base_qs
            .order_by('manufacturer__name', 'model__name')
            .values_list('manufacturer__name', 'model__name')
            .distinct()
        )
        make_models_map = {}
        for make, model in make_models_qs:
            make_models_map.setdefault(make, [])
            if model not in make_models_map[make]:
                make_models_map[make].append(model)

        # --- All auctions for the switcher dropdown ---
        all_auctions = (
            ApiCar.objects
            .exclude(auction_name__isnull=True).exclude(auction_name='')
            .values_list('auction_name', flat=True)
            .distinct()
            .order_by('auction_name')
        )

        # --- Parse active filters from GET params ---
        f_make      = request.GET.get('make', '').strip()
        f_model     = request.GET.get('model', '').strip()
        f_year_min  = request.GET.get('year_min', '').strip()
        f_year_max  = request.GET.get('year_max', '').strip()
        f_status    = request.GET.get('status', '').strip()
        f_fuels     = request.GET.getlist('fuel')  # multi-select list

        # --- Apply filters ---
        cars_qs = base_qs
        if f_make:
            cars_qs = cars_qs.filter(manufacturer__name=f_make)
        if f_model:
            cars_qs = cars_qs.filter(model__name=f_model)
        if f_year_min:
            try:
                cars_qs = cars_qs.filter(year__gte=int(f_year_min))
            except ValueError:
                pass
        if f_year_max:
            try:
                cars_qs = cars_qs.filter(year__lte=int(f_year_max))
            except ValueError:
                pass
        if f_status:
            cars_qs = cars_qs.filter(status=f_status)
        if f_fuels:
            cars_qs = cars_qs.filter(fuel__in=f_fuels)

        cars_qs = cars_qs.order_by('manufacturer__name', 'year')

        paginator   = Paginator(cars_qs, 24)
        page_number = request.GET.get('page', 1)
        page_obj    = paginator.get_page(page_number)
        exports     = PdfExport.objects.all().order_by('-created_at')
        has_pending = exports.filter(status=PdfExport.STATUS_PENDING).exists()

        # Build a query-string fragment that preserves all filters (for pagination links)
        active_filters = {k: v for k, v in {
            'make': f_make, 'model': f_model,
            'year_min': f_year_min, 'year_max': f_year_max,
            'status': f_status,
        }.items() if v}
        filter_qs_str = urlencode(active_filters)
        if f_fuels:
            filter_qs_str += ('&' if filter_qs_str else '') + '&'.join(f'fuel={v}' for v in f_fuels)
        filter_qs = ('&' + filter_qs_str) if filter_qs_str else ''

        return render(request, 'cars/pdf_export_panel.html', {
            'step': 'pick',
            'auction_name': auction_name,
            'all_auctions': list(all_auctions),
            'cars': page_obj,
            'page_obj': page_obj,
            'filter_makes': list(filter_makes),
            'filter_years': list(filter_years),
            'filter_fuels': list(filter_fuels),
            'make_models_map_json': json.dumps(make_models_map),
            'f_make': f_make,
            'f_model': f_model,
            'f_year_min': f_year_min,
            'f_year_max': f_year_max,
            'f_status': f_status,
            'f_fuels': f_fuels,
            'filter_qs': filter_qs,
            'active_filter_count': len(active_filters) + (1 if f_fuels else 0),
            'exports': exports,
            'has_pending': has_pending,
            'STATUS_PENDING':  PdfExport.STATUS_PENDING,
            'STATUS_COMPLETE': PdfExport.STATUS_COMPLETE,
            'STATUS_FAILED':   PdfExport.STATUS_FAILED,
        })

    # ── GET (landing) → auction picker + export history ──────────────────
    available_auctions = (
        ApiCar.objects
        .exclude(auction_name__isnull=True).exclude(auction_name='')
        .values('auction_name')
        .annotate(total=Count('pk'), with_entry=Count('entry'))
        .order_by('auction_name')
    )

    exports = PdfExport.objects.all().order_by('-created_at')
    has_pending = exports.filter(status=PdfExport.STATUS_PENDING).exists()

    return render(request, 'cars/pdf_export_panel.html', {
        'step': 'choose',
        'available_auctions': available_auctions,
        'exports': exports,
        'has_pending': has_pending,
        'STATUS_PENDING':  PdfExport.STATUS_PENDING,
        'STATUS_COMPLETE': PdfExport.STATUS_COMPLETE,
        'STATUS_FAILED':   PdfExport.STATUS_FAILED,
    })


def pdf_export_delete(request, pk):
    """Delete a single PdfExport record (staff only, POST)."""
    from .models import PdfExport
    if not request.user.is_staff:
        return HttpResponse("غير مصرح.", status=403)
    if request.method == 'POST':
        obj = get_object_or_404(PdfExport, pk=pk)
        if obj.pdf_file:
            obj.pdf_file.delete(save=False)
        obj.delete()
        messages.success(request, "تم حذف سجل التصدير.")
    return redirect('pdf_export_panel')


from django.views.decorators.csrf import csrf_exempt  # noqa: E402 (already imported above, safe)

@csrf_exempt
def ofleet_webhook(request):
    """
    Receives the completion callback from ofleet0.com.

    ofleet POSTs here when an export job finishes. The payload:
        {
            "job_id": 146,
            "status": "done",          # or "failed"
            "files": [
                {"label": "Hyundai", "download_url": "https://ofleet0.com/..."}
            ],
            "error_msg": null
        }

    We find the matching pending PdfExport record and call process_webhook_payload
    to download the PDFs and update the DB.
    """
    import json as _json
    from .models import PdfExport

    logger.info(
        "ofleet_webhook called: method=%s body=%s",
        request.method,
        request.body[:500] if request.body else b'',
    )

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = _json.loads(request.body)
    except Exception:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    schema = getattr(connection, 'schema_name', '')
    logger.info("ofleet_webhook: schema=%s data=%s", schema, data)

    # Find the most recent pending record for this schema to link files to it
    parent = (
        PdfExport.objects
        .filter(schema_name=schema, status=PdfExport.STATUS_PENDING)
        .order_by('-created_at')
        .first()
    )
    parent_id = parent.pk if parent else None

    process_webhook_payload(data, schema_name=schema, parent_export_id=parent_id)

    return JsonResponse({'ok': True})




@ensure_csrf_cookie
@cache_control(public=True, max_age=120)
def car_list(request):
    # For anonymous users, try to serve a cached full response to reduce DB load.
    # Use a stable hash of sorted GET params so param-order variants share the same key.
    schema = getattr(connection, 'schema_name', 'public')
    cache_key = None
    if not request.user.is_authenticated:
        _params = {k: sorted(v) for k, v in request.GET.lists()}
        _params_hash = hashlib.md5(
            json.dumps(_params, sort_keys=True).encode()
        ).hexdigest()
        _variant = 'htmx' if getattr(request, 'htmx', False) else 'full'
        cache_key = f"car_list_v3:{schema}:{_variant}:{_params_hash}"
        cached_html = cache.get(cache_key)
        if cached_html:
            return HttpResponse(cached_html)

    qs = _exclude_expired_auctions(
        ApiCar.objects.select_related(
            'manufacturer', 'model', 'badge', 'color', 'body', 'category'
        ).only(
            'id', 'title', 'slug', 'image', 'images', 'price', 'year', 'mileage',
            'status', 'lot_number', 'vin', 'fuel', 'transmission', 'address',
            'auction_date', 'auction_name', 'condition', 'created_at', 'is_new',
            'manufacturer__id', 'manufacturer__name', 'manufacturer__name_ar',
            'manufacturer__logo',
            'model__id', 'model__name', 'model__name_ar',
            'badge__id', 'badge__name',
            'color__id', 'color__name',
            'body__id', 'body__name',
            'category__id', 'category__name',
        )
    )

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(lot_number__icontains=q) | Q(vin__icontains=q)
            | Q(manufacturer__name__icontains=q) | Q(model__name__icontains=q)
            | Q(badge__name__icontains=q)
        )

    # Drop empty strings — hero/drawer forms can emit `?manufacturer=` when the
    # cascade is left empty, and `int('')` would explode on the SQL filter.
    sel_manufacturers = [v for v in request.GET.getlist('manufacturer') if v]
    if sel_manufacturers:
        qs = qs.filter(manufacturer_id__in=sel_manufacturers)

    sel_models = [v for v in request.GET.getlist('model') if v]
    if sel_models:
        qs = qs.filter(model_id__in=sel_models)

    sel_badges = [v for v in request.GET.getlist('badge') if v]
    if sel_badges:
        qs = qs.filter(badge_id__in=sel_badges)

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

    sel_colors = request.GET.getlist('color')
    if sel_colors:
        qs = qs.filter(color_id__in=sel_colors)

    sel_body_types = request.GET.getlist('body_type')
    if sel_body_types:
        qs = qs.filter(body__name__in=sel_body_types)

    sel_fuels = request.GET.getlist('fuel')
    if sel_fuels:
        qs = qs.filter(fuel__in=sel_fuels)

    sel_transmissions = request.GET.getlist('transmission')
    if sel_transmissions:
        qs = qs.filter(transmission__in=sel_transmissions)

    sel_seat_counts = request.GET.getlist('seat_count')
    if sel_seat_counts:
        qs = qs.filter(seat_count__in=sel_seat_counts)

    sel_seat_colors = request.GET.getlist('seat_color')
    if sel_seat_colors:
        qs = qs.filter(seat_color_id__in=sel_seat_colors)

    sel_auction_names = request.GET.getlist('auction_name')
    if sel_auction_names:
        qs = qs.filter(auction_name__in=sel_auction_names)

    car_type = request.GET.get('car_type')
    if car_type == 'auction':
        qs = qs.filter(category__name='auction')
    elif car_type == 'cars':
        qs = qs.exclude(category__name='auction').exclude(body__name='truck')
    elif car_type == 'truck':
        qs = qs.exclude(category__name='auction').filter(body__name='truck')

    sel_statuses = request.GET.getlist('status')
    if sel_statuses:
        qs = qs.filter(status__in=sel_statuses)

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

    sort = request.GET.get('sort')
    allowed_sorts = ['-created_at', 'price', '-price', '-year', 'year', 'mileage', '-mileage']
    if sort in allowed_sorts:
        # User explicitly chose a sort — honour it directly.
        qs = qs.order_by(sort)
    else:
        # Default: lead with the most appealing manufacturers, newest first.
        qs = _order_by_appeal(qs, '-created_at')

    # Cache the paginator COUNT per unique filter combination (excludes sort/page
    # which don't affect the total count).  This avoids a full-table COUNT(*) on
    # every cache miss for different sort orders.
    _count_params = {k: sorted(v) for k, v in request.GET.lists() if k not in ('sort', 'page')}
    _count_hash = hashlib.md5(
        json.dumps(_count_params, sort_keys=True).encode()
    ).hexdigest()
    _count_cache_key = f"car_list_v2:count:{schema}:{_count_hash}"
    _cached_count = cache.get(_count_cache_key)

    class _CachedCountPaginator(Paginator):
        """Paginator that uses a pre-cached count to avoid a DB COUNT(*) query.

        Uses a two-level approach:
          1. Redis/LocMem cache across requests (keyed by filter params).
          2. Instance-level _count_memo so that multiple accesses within the
             same request (Django calls .count several times for num_pages,
             page_range, etc.) never hit the DB more than once.
        """
        _count_memo = None

        @property
        def count(self):
            if self._count_memo is not None:
                return self._count_memo
            if _cached_count is not None:
                self._count_memo = _cached_count
                return self._count_memo
            c = super().count
            self._count_memo = c
            cache.set(_count_cache_key, c, 60 * 5)
            return c

    paginator = _CachedCountPaginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    query_params = request.GET.copy()
    query_params.pop('page', None)
    query_string = query_params.urlencode()

    # ── Filter options – cache static-ish lookups for 15 minutes ──
    now = timezone.now()
    car_type = request.GET.get('car_type')

    if car_type == 'auction':
        # Use flat values_list to avoid a correlated subquery — cached 15 min
        _auction_mfr_key = f"car_list_v2:auction_manufacturers:{schema}"
        _static_cache_key = f"car_list_v2:static_filters_auction:{schema}"
        _pop_mfr_key = f"car_list_v2:popular_manufacturers_auction:{schema}"

        manufacturers      = cache.get(_auction_mfr_key)
        static_filters     = cache.get(_static_cache_key)
        popular_manufacturers = cache.get(_pop_mfr_key)

        # If ANY of the three auction caches is cold, rebuild all from one scan
        if manufacturers is None or static_filters is None or popular_manufacturers is None:
            _auction_qs = ApiCar.objects.filter(category__name='auction').exclude(auction_date__lt=now)

            # --- manufacturers sidebar list ---
            _mfr_ids = set(_auction_qs.values_list('manufacturer_id', flat=True).distinct())
            manufacturers = list(
                Manufacturer.objects.filter(id__in=_mfr_ids)
                .annotate(car_count=Count(
                    'apicar',
                    filter=Q(apicar__category__name='auction') & ~Q(apicar__auction_date__lt=now),
                ))
                .order_by('-car_count')
            )
            cache.set(_auction_mfr_key, manufacturers, 60 * 15)

            # --- static filter dimensions (DISTINCT queries — no full row scan) ---
            _years      = list(_auction_qs.order_by('-year').values_list('year', flat=True).distinct()[:30])
            _body_ids   = set(_auction_qs.values_list('body_id', flat=True).distinct())
            _fuels      = sorted(v for v in _auction_qs.values_list('fuel', flat=True).distinct() if v)[:15]
            _trans      = sorted(v for v in _auction_qs.values_list('transmission', flat=True).distinct() if v)
            # seat_count is a CharField; sort numerically so "10" doesn't come
            # before "2", and skip empties / zero-seat rows.
            def _seat_sort_key(v):
                s = str(v)
                if s.replace('.', '', 1).replace('-', '', 1).isdigit():
                    return (float(v), s)
                return (float('inf'), s)
            _seats      = sorted(
                (v for v in _auction_qs.values_list('seat_count', flat=True).distinct()
                 if v and str(v).strip() not in ('0', '0.0') and not (str(v).replace('.', '', 1).isdigit() and float(v) == 0)),
                key=_seat_sort_key,
            )
            _color_ids  = set(_auction_qs.values_list('color_id', flat=True).distinct())
            _scolor_ids = set(_auction_qs.values_list('seat_color_id', flat=True).distinct())
            _anames     = sorted(v for v in _auction_qs.values_list('auction_name', flat=True).distinct() if v)

            static_filters = {
                'years': _years,
                'body_types': list(BodyType.objects.filter(id__in=_body_ids).order_by('name')),
                'fuels': _fuels,
                'transmissions': _trans,
                'seat_counts': _seats,
                'colors': list(CarColor.objects.filter(id__in=_color_ids).order_by('name')),
                'seat_colors': list(CarSeatColor.objects.filter(id__in=_scolor_ids).order_by('name')),
                'auction_names': _anames,
            }
            cache.set(_static_cache_key, static_filters, 60 * 60)  # 60 min — changes only on import

            # --- popular manufacturers: reuse already-annotated manufacturers list ---
            popular_manufacturers = sorted(manufacturers, key=lambda m: m.car_count, reverse=True)
            cache.set(_pop_mfr_key, popular_manufacturers, 60 * 15)
    else:
        _mfr_cache_suffix = {'cars': 'cars', 'truck': 'truck'}.get(car_type, 'all')
        _mfr_cache_key = f"car_list_v3:manufacturers_{_mfr_cache_suffix}"
        manufacturers = cache.get(_mfr_cache_key)
        if manufacturers is None:
            if car_type == 'truck':
                _mfr_count_filter = ~Q(apicar__category__name='auction') & Q(apicar__body__name='truck')
            elif car_type == 'cars':
                _mfr_count_filter = ~Q(apicar__category__name='auction') & ~Q(apicar__body__name='truck')
            else:
                _mfr_count_filter = ~Q(apicar__category__name='auction', apicar__auction_date__lt=now)
            manufacturers = list(
                Manufacturer.objects.annotate(car_count=Count('apicar', filter=_mfr_count_filter))
                .filter(car_count__gt=0)
                .order_by('-car_count')
            )
            cache.set(_mfr_cache_key, manufacturers, 60 * 15)

    # Only load models/badges when manufacturer/model is selected, scoped to car_type
    if sel_manufacturers:
        _mfr_key_part = sel_manufacturers[0] if len(sel_manufacturers) == 1 else '-'.join(sorted(sel_manufacturers))
        if car_type == 'auction':
            _models_cache_key = f"car_list_v2:models_auction_cnt:{_mfr_key_part}"
            models_qs = cache.get(_models_cache_key)
            if models_qs is None:
                _auction_model_ids = list(
                    ApiCar.objects.filter(
                        category__name='auction', manufacturer_id__in=sel_manufacturers
                    ).exclude(auction_date__lt=now)
                    .values_list('model_id', flat=True).distinct()
                )
                models_qs = list(
                    CarModel.objects.filter(id__in=_auction_model_ids)
                    .annotate(car_count=Count(
                        'apicar',
                        filter=Q(apicar__category__name='auction') & ~Q(apicar__auction_date__lt=now) & Q(apicar__manufacturer_id__in=sel_manufacturers),
                    ))
                    .order_by('-car_count')
                )
                for m in models_qs:
                    setattr(m, 'name_ar', car_models_dict.get(m.name.lower()))
                cache.set(_models_cache_key, models_qs, 60 * 15)
        elif car_type == 'cars':
            _models_cache_key = f"car_list_v2:models_cars_cnt:{_mfr_key_part}"
            models_qs = cache.get(_models_cache_key)
            if models_qs is None:
                _cars_model_ids = list(
                    ApiCar.objects.filter(manufacturer_id__in=sel_manufacturers)
                    .exclude(category__name='auction')
                    .exclude(body__name='truck')
                    .values_list('model_id', flat=True).distinct()
                )
                models_qs = list(
                    CarModel.objects.filter(id__in=_cars_model_ids)
                    .annotate(car_count=Count(
                        'apicar',
                        filter=~Q(apicar__category__name='auction') & ~Q(apicar__body__name='truck') & Q(apicar__manufacturer_id__in=sel_manufacturers),
                    ))
                    .order_by('-car_count')
                )
                for m in models_qs:
                    setattr(m, 'name_ar', car_models_dict.get(m.name.lower()))
                cache.set(_models_cache_key, models_qs, 60 * 15)
        elif car_type == 'truck':
            _models_cache_key = f"car_list_v2:models_truck_cnt:{_mfr_key_part}"
            models_qs = cache.get(_models_cache_key)
            if models_qs is None:
                _truck_model_ids = list(
                    ApiCar.objects.filter(manufacturer_id__in=sel_manufacturers, body__name='truck')
                    .exclude(category__name='auction')
                    .values_list('model_id', flat=True).distinct()
                )
                models_qs = list(
                    CarModel.objects.filter(id__in=_truck_model_ids)
                    .annotate(car_count=Count(
                        'apicar',
                        filter=~Q(apicar__category__name='auction') & Q(apicar__body__name='truck') & Q(apicar__manufacturer_id__in=sel_manufacturers),
                    ))
                    .order_by('-car_count')
                )
                for m in models_qs:
                    setattr(m, 'name_ar', car_models_dict.get(m.name.lower()))
                cache.set(_models_cache_key, models_qs, 60 * 15)
        else:
            _models_cache_key = f"car_list_v2:models_cnt:{_mfr_key_part}"
            models_qs = cache.get(_models_cache_key)
            if models_qs is None:
                _model_ids = list(
                    ApiCar.objects.filter(manufacturer_id__in=sel_manufacturers)
                    .exclude(category__name='auction', auction_date__lt=now)
                    .values_list('model_id', flat=True).distinct()
                )
                models_qs = list(
                    CarModel.objects.filter(id__in=_model_ids)
                    .annotate(car_count=Count(
                        'apicar',
                        filter=~Q(apicar__category__name='auction', apicar__auction_date__lt=now) & Q(apicar__manufacturer_id__in=sel_manufacturers),
                    ))
                    .order_by('-car_count')
                )
                for m in models_qs:
                    setattr(m, 'name_ar', car_models_dict.get(m.name.lower()))
                cache.set(_models_cache_key, models_qs, 60 * 15)
    else:
        models_qs = []

    if sel_models:
        _mdl_key_part = sel_models[0] if len(sel_models) == 1 else '-'.join(sorted(sel_models))
        _badges_cache_key = f"car_list_v2:badges_cnt:{_mdl_key_part}:{car_type or 'all'}"
        badges = cache.get(_badges_cache_key)
        if badges is None:
            if car_type == 'auction':
                _badge_filter = Q(apicar__category__name='auction') & ~Q(apicar__auction_date__lt=now) & Q(apicar__model_id__in=sel_models)
            elif car_type == 'cars':
                _badge_filter = ~Q(apicar__category__name='auction') & ~Q(apicar__body__name='truck') & Q(apicar__model_id__in=sel_models)
            elif car_type == 'truck':
                _badge_filter = ~Q(apicar__category__name='auction') & Q(apicar__body__name='truck') & Q(apicar__model_id__in=sel_models)
            else:
                _badge_filter = ~Q(apicar__category__name='auction', apicar__auction_date__lt=now) & Q(apicar__model_id__in=sel_models)
            badges = list(
                CarBadge.objects.filter(model_id__in=sel_models)
                .annotate(car_count=Count('apicar', filter=_badge_filter))
                .filter(car_count__gt=0)
                .distinct().order_by('-car_count')
            )
            cache.set(_badges_cache_key, badges, 60 * 15)
    else:
        badges = []

    # Static lookup lists — scoped to the current car_type, cached 30 min
    # Static lookup lists — for non-auction only (auction path handled above)
    if car_type != 'auction':
        if car_type == 'cars':
            _static_cache_key = f"car_list_v2:static_filters_cars:{schema}"
            _base_qs = ApiCar.objects.exclude(category__name='auction').exclude(body__name='truck')
        elif car_type == 'truck':
            _static_cache_key = f"car_list_v2:static_filters_truck:{schema}"
            _base_qs = ApiCar.objects.exclude(category__name='auction').filter(body__name='truck')
        else:
            _static_cache_key = f"car_list_v2:static_filters_all:{schema}"
            _base_qs = ApiCar.objects.exclude(category__name='auction', auction_date__lt=now)

        static_filters = cache.get(_static_cache_key)
        if static_filters is None:
            _years      = list(_base_qs.order_by('-year').values_list('year', flat=True).distinct()[:30])
            _body_ids   = set(_base_qs.values_list('body_id', flat=True).distinct())
            _fuels      = sorted(v for v in _base_qs.values_list('fuel', flat=True).distinct() if v)[:15]
            _trans      = sorted(v for v in _base_qs.values_list('transmission', flat=True).distinct() if v)
            # seat_count is a CharField; sort numerically so "10" doesn't come
            # before "2", and skip empties / zero-seat rows.
            def _seat_sort_key(v):
                s = str(v)
                if s.replace('.', '', 1).replace('-', '', 1).isdigit():
                    return (float(v), s)
                return (float('inf'), s)
            _seats      = sorted(
                (v for v in _base_qs.values_list('seat_count', flat=True).distinct()
                 if v and str(v).strip() not in ('0', '0.0') and not (str(v).replace('.', '', 1).isdigit() and float(v) == 0)),
                key=_seat_sort_key,
            )
            _color_ids  = set(_base_qs.values_list('color_id', flat=True).distinct())
            _scolor_ids = set(_base_qs.values_list('seat_color_id', flat=True).distinct())
            static_filters = {
                'years': _years,
                'body_types': list(BodyType.objects.filter(id__in=_body_ids).order_by('name')),
                'fuels': _fuels,
                'transmissions': _trans,
                'seat_counts': _seats,
                'colors': list(CarColor.objects.filter(id__in=_color_ids).order_by('name')),
                'seat_colors': list(CarSeatColor.objects.filter(id__in=_scolor_ids).order_by('name')),
                'auction_names': [],
            }
            cache.set(_static_cache_key, static_filters, 60 * 60)  # 60 min — changes only on import

    years         = static_filters['years']
    body_types    = static_filters['body_types']
    fuels         = static_filters['fuels']
    transmissions = static_filters['transmissions']
    seat_counts   = static_filters['seat_counts']
    colors        = static_filters['colors']
    seat_colors   = static_filters['seat_colors']
    auction_names = static_filters['auction_names']

    # Counts for tabs – single aggregate query, cached 5 min (global, not filter-specific)
    _tab_count_key = f"car_list_v2:tab_counts_v3:{schema}"
    tab_counts = cache.get(_tab_count_key)
    if tab_counts is None:
        _tab_base = ApiCar.objects.exclude(category__name='auction', auction_date__lt=now)
        tab_counts = _tab_base.aggregate(
            count_all=Count('id'),
            count_auction=Count('id', filter=Q(category__name='auction')),
            count_cars=Count('id', filter=~Q(category__name='auction') & ~Q(body__name='truck')),
            count_truck=Count('id', filter=~Q(category__name='auction') & Q(body__name='truck')),
        )
        cache.set(_tab_count_key, tab_counts, 60 * 5)
    count_all = tab_counts['count_all']
    count_cars = tab_counts['count_cars']
    count_auction = tab_counts['count_auction']
    count_truck = tab_counts['count_truck']

    # Site cars count for the showroom tab — cached 10 min
    # site_cars_count  = admin-uploaded SiteCars (no external_id)  → "سياراتنا" tab
    # damaged_cars_count = HappyCar imports (external_id hc_*)     → "سيارات مصدومة" tab
    _site_cars_tab_key = f"car_list_v2:site_cars_count:{schema}"
    site_cars_count = cache.get(_site_cars_tab_key)
    _damaged_cars_tab_key = f"car_list_v2:damaged_cars_count:{schema}"
    damaged_cars_count = cache.get(_damaged_cars_tab_key)
    if site_cars_count is None or damaged_cars_count is None:
        try:
            from site_cars.models import SiteCar
            site_cars_count = (SiteCar.objects
                               .exclude(external_id__startswith='hc_')
                               .filter(status='available').count())
            damaged_cars_count = (SiteCar.objects
                                  .filter(external_id__startswith='hc_').count())
        except Exception:
            site_cars_count = 0
            damaged_cars_count = 0
        cache.set(_site_cars_tab_key, site_cars_count, 60 * 10)
        cache.set(_damaged_cars_tab_key, damaged_cars_count, 60 * 10)

    # Popular manufacturers – auction path already set above; non-auction handled here
    if car_type != 'auction':
        _pop_mfr_key = f"car_list_v3:popular_manufacturers:{schema}"
        popular_manufacturers = cache.get(_pop_mfr_key)
        if popular_manufacturers is None:
            popular_manufacturers = list(
                Manufacturer.objects.annotate(
                    car_count=Count(
                        'apicar',
                        filter=~Q(apicar__category__name='auction', apicar__auction_date__lt=now),
                    )
                )
                .filter(car_count__gt=0)
                .order_by('-car_count')
            )
            cache.set(_pop_mfr_key, popular_manufacturers, 60 * 15)
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
        'count_truck': count_truck,
        'site_cars_count': site_cars_count,
        'damaged_cars_count': damaged_cars_count,
        'selected_year_from': request.GET.get('year_from', ''),
        'selected_year_to': request.GET.get('year_to', ''),
        'sel_manufacturers': sel_manufacturers,
        'sel_models':        sel_models,
        'sel_badges':        sel_badges,
        'sel_fuels':         request.GET.getlist('fuel'),
        'sel_transmissions': request.GET.getlist('transmission'),
        'sel_body_types':    request.GET.getlist('body_type'),
        'sel_colors':        request.GET.getlist('color'),
        'sel_statuses':      request.GET.getlist('status'),
        'sel_seat_counts':   request.GET.getlist('seat_count'),
        'sel_seat_colors':   request.GET.getlist('seat_color'),
        'sel_auction_names': request.GET.getlist('auction_name'),
    }
    # HTMX partial request — return only the car grid fragment
    if request.htmx:
        resp = render(request, 'cars/_car_list_results.html', context)
        resp['Vary'] = 'HX-Request'
        return resp

    response = render(request, 'cars/car_list.html', context)
    response['Vary'] = 'HX-Request'
    # Cache the rendered HTML for anonymous users only
    try:
        if cache_key and not request.user.is_authenticated:
            cache.set(cache_key, response.content, 300)  # cache 5 min
    except Exception:
        # Don't let caching errors break the response
        pass

    return response


def expired_auctions(request):
    now = timezone.now()
    qs = ApiCar.objects.select_related(
        'manufacturer', 'model', 'badge', 'color', 'body'
    ).filter(category__name='auction', auction_date__lt=now).only(
        'id', 'title', 'slug', 'image', 'price', 'year', 'mileage',
        'status', 'lot_number', 'auction_date', 'auction_name', 'created_at',
        'manufacturer__id', 'manufacturer__name', 'manufacturer__name_ar',
        'model__id', 'model__name', 'model__name_ar',
        'badge__id', 'badge__name',
        'color__id', 'color__name',
        'body__id', 'body__name',
    )

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

    paginator = Paginator(qs, 20)  # 20 items per page
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
    }
    return render(request, 'cars/expired_auctions.html', context)


def api_models_by_manufacturer(request):
    manufacturer_id = request.GET.get('manufacturer_id')
    if not manufacturer_id:
        return JsonResponse([], safe=False)

    # Optionally scope/cache by car_type and language so localized responses
    # don't override each other. We'll compute car_type/lang before building
    # the cache key.
    car_type = request.GET.get('car_type')
    lang = request.GET.get('lang') or getattr(request, 'LANGUAGE_CODE', '') or ''
    schema = getattr(connection, 'schema_name', 'public')
    _cache_key = f"api_models_v4:{schema}:{manufacturer_id}:ct:{car_type or 'all'}:lang:{lang or 'en'}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return JsonResponse(cached, safe=False)

    # Get manufacturer info for logo
    manufacturer_logo = None
    try:
        manufacturer = Manufacturer.objects.get(id=manufacturer_id)
        
        if manufacturer.logo:
            try:
                logo_string = str(manufacturer.logo).strip()
                
                # Check if logo is a file field (has .url attribute) or a string path
                if hasattr(manufacturer.logo, 'url'):
                    manufacturer_logo = request.build_absolute_uri(manufacturer.logo.url)
                else:
                    if logo_string.startswith('/'):
                        manufacturer_logo = request.build_absolute_uri(logo_string)
                    elif logo_string.startswith('http'):
                        manufacturer_logo = logo_string
                    else:
                        from django.conf import settings
                        if hasattr(settings, 'MEDIA_URL'):
                            manufacturer_logo = request.build_absolute_uri(settings.MEDIA_URL + logo_string)
                        else:
                            manufacturer_logo = request.build_absolute_uri('/media/' + logo_string)
            except Exception:
                manufacturer_logo = None
    except Manufacturer.DoesNotExist:
        pass
    except Exception:
        pass
    
    try:
        # Optionally scope models to car_type (auction or cars) and localize names
        now = timezone.now()

        if car_type == 'auction':
            model_ids = list(
                ApiCar.objects.filter(manufacturer_id=manufacturer_id, category__name='auction')
                .exclude(auction_date__lt=now)
                .values_list('model_id', flat=True).distinct()
            )
            qs = CarModel.objects.filter(id__in=model_ids)
            qs = qs.annotate(car_count=Count('apicar', filter=Q(apicar__category__name='auction') & ~Q(apicar__auction_date__lt=now)))
        elif car_type == 'cars':
            model_ids = list(
                ApiCar.objects.filter(manufacturer_id=manufacturer_id)
                .exclude(category__name='auction')
                .exclude(body__name='truck')
                .values_list('model_id', flat=True).distinct()
            )
            qs = CarModel.objects.filter(id__in=model_ids)
            qs = qs.annotate(car_count=Count('apicar', filter=~Q(apicar__category__name='auction') & ~Q(apicar__body__name='truck')))
        elif car_type == 'truck':
            model_ids = list(
                ApiCar.objects.filter(manufacturer_id=manufacturer_id, body__name='truck')
                .exclude(category__name='auction')
                .values_list('model_id', flat=True).distinct()
            )
            qs = CarModel.objects.filter(id__in=model_ids)
            qs = qs.annotate(car_count=Count('apicar', filter=~Q(apicar__category__name='auction') & Q(apicar__body__name='truck')))
        else:
            model_ids = list(
                ApiCar.objects.filter(manufacturer_id=manufacturer_id)
                .exclude(category__name='auction', auction_date__lt=now)
                .values_list('model_id', flat=True).distinct()
            )
            qs = CarModel.objects.filter(id__in=model_ids)
            qs = qs.annotate(car_count=Count(
                'apicar',
                filter=~Q(apicar__category__name='auction', apicar__auction_date__lt=now) & Q(apicar__manufacturer_id=manufacturer_id),
            ))

        qs = qs.order_by('-car_count')

        from cars.templatetags.custom_filters import pretty_en
        models = []
        for m in qs:
            name_ar = getattr(m, 'name_ar', None) or car_models_dict.get(m.name.lower()) or m.name
            name_en = pretty_en(m.name)
            if lang and lang.startswith('ar'):
                display_name = name_ar
            else:
                display_name = name_en
            models.append({
                'id': m.id,
                'name': display_name,
                'name_ar': name_ar,
                'name_en': name_en,
                'car_count': getattr(m, 'car_count', 0),
                'manufacturer_logo': manufacturer_logo,
            })

        cache.set(_cache_key, models, 60 * 30)  # 30 minutes
        return JsonResponse(models, safe=False)
    except Exception:
        return JsonResponse([], safe=False)

def api_badges_by_model(request):
    model_id = request.GET.get('model_id')
    if not model_id:
        return JsonResponse([], safe=False)

    schema = getattr(connection, 'schema_name', 'public')
    car_type_key = request.GET.get('car_type') or 'all'
    _cache_key = f"api_badges_v2:{schema}:{model_id}:ct:{car_type_key}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return JsonResponse(cached, safe=False)

    # Scope badges to car_type via ApiCar membership so only badges that have
    # at least one matching car are returned.
    car_type = request.GET.get('car_type')
    now = timezone.now()
    if car_type == 'auction':
        badge_ids = ApiCar.objects.filter(
            model_id=model_id, category__name='auction'
        ).exclude(auction_date__lt=now).values_list('badge_id', flat=True).distinct()
        _badge_count_filter = Q(apicar__category__name='auction') & ~Q(apicar__auction_date__lt=now) & Q(apicar__model_id=model_id)
    elif car_type == 'cars':
        badge_ids = ApiCar.objects.filter(model_id=model_id).exclude(
            category__name='auction'
        ).exclude(body__name='truck').values_list('badge_id', flat=True).distinct()
        _badge_count_filter = ~Q(apicar__category__name='auction') & ~Q(apicar__body__name='truck') & Q(apicar__model_id=model_id)
    elif car_type == 'truck':
        badge_ids = ApiCar.objects.filter(
            model_id=model_id, body__name='truck'
        ).exclude(category__name='auction').values_list('badge_id', flat=True).distinct()
        _badge_count_filter = ~Q(apicar__category__name='auction') & Q(apicar__body__name='truck') & Q(apicar__model_id=model_id)
    else:
        badge_ids = ApiCar.objects.filter(model_id=model_id).exclude(
            category__name='auction', auction_date__lt=now
        ).values_list('badge_id', flat=True).distinct()
        _badge_count_filter = ~Q(apicar__category__name='auction', apicar__auction_date__lt=now) & Q(apicar__model_id=model_id)

    badges = list(
        CarBadge.objects.filter(id__in=badge_ids)
        .annotate(car_count=Count('apicar', filter=_badge_count_filter))
        .order_by('-car_count').values('id', 'name', 'car_count')
    )
    cache.set(_cache_key, badges, 60 * 30)  # 30 minutes
    return JsonResponse(badges, safe=False)


def _get_similar_cars(car, count=6):
    """
    Return up to `count` similar cars matching make + model + badge + year.
    Falls back gracefully if not enough exact matches:
      1. make + model + badge + year        (exact)
      2. make + model + badge               (any year)
      3. make + model                       (any badge/year)
      4. make only                          (fill remaining slots)
    """
    base_qs = (
        ApiCar.objects
        .filter(manufacturer=car.manufacturer, status='available')
        .exclude(pk=car.pk)
        .select_related('manufacturer', 'model', 'badge')
        .order_by('-year', '-created_at')
    )

    results = []
    seen_ids = set()

    def _add(qs, limit):
        for c in qs[:limit]:
            if c.pk not in seen_ids:
                seen_ids.add(c.pk)
                results.append(c)

    remaining = count

    # 1 — exact: same model + badge + year
    if car.model_id and car.badge_id and car.year:
        _add(base_qs.filter(model=car.model, badge=car.badge, year=car.year), remaining)
        remaining = count - len(results)

    # 2 — same model + badge, any year
    if remaining and car.model_id and car.badge_id:
        _add(base_qs.filter(model=car.model, badge=car.badge).exclude(pk__in=seen_ids), remaining)
        remaining = count - len(results)

    # 3 — same model, any badge/year
    if remaining and car.model_id:
        _add(base_qs.filter(model=car.model).exclude(pk__in=seen_ids), remaining)
        remaining = count - len(results)

    # 4 — same make only (fill remaining slots)
    if remaining:
        _add(base_qs.exclude(pk__in=seen_ids), remaining)

    return results


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

    insp = _build_inspection_context(car.extra_features or {})

    context = {
        'car': car,
        'ratings': ratings,
        'avg_rating': avg_rating,
        'user_rating': user_rating,
        'pending_ratings': pending_ratings,
        'similar_cars': _get_similar_cars(car),
        'inspection_legend': [
            ('P',   'وكالة',        'Dealer'),
            ('A',   'وكالة',        'Dealer'),
            ('Q',   'وكالة',        'Dealer'),
            ('W',   'رش',           'Paint'),
            ('X',   'تغيير بدون رش', 'Replaced (no paint)'),
            ('XXP', 'مغير ومرشوش',   'Replaced & Painted'),
            ('PP',  'رش تجميلي',    'Cosmetic paint'),
            ('WR',  'رش',           'Paint'),
            ('R',   'وكالة',        'Dealer'),
            ('WU',  'رش',           'Paint'),
        ],
        'insp': insp,
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
    """Toggle car in user's wishlist (session-based, no login required)"""
    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key

    try:
        car = get_object_or_404(ApiCar, pk=car_id)

        wishlist_item, created = Wishlist.objects.get_or_create(
            session_key=session_key,
            car=car,
        )

        if not created:
            wishlist_item.delete()
            in_wishlist = False
        else:
            in_wishlist = True

        return JsonResponse({'in_wishlist': in_wishlist})

    except Exception as e:
        print(f"Error in toggle_wishlist: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': f'حدث خطأ: {str(e)}'}, status=500)


@ensure_csrf_cookie
def wishlist(request):
    """Show session wishlist"""
    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key

    wishlist_items = Wishlist.objects.filter(
        session_key=session_key
    ).select_related('car', 'car__manufacturer', 'car__model').order_by('-created_at')

    valid_items = []
    for item in wishlist_items:
        if _exclude_expired_auctions(ApiCar.objects.filter(pk=item.car.pk)).exists():
            valid_items.append(item)
        else:
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
    """Get session wishlist count"""
    if not request.session.session_key:
        return JsonResponse({'count': 0})

    session_key = request.session.session_key
    cache_key = f"wishlist_count_{session_key}"
    count = cache.get(cache_key)
    if count is not None:
        return JsonResponse({'count': count})

    try:
        count = Wishlist.objects.filter(session_key=session_key).count()
        cache.set(cache_key, count, 60)
        return JsonResponse({'count': count})
    except Exception:
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


_ENCAR_BASE_IMG  = "https://ci.encar.com"
_SEDAN_IMG       = "/static/images/car_sedan.png"
_TRUCK_IMG       = "/static/images/car_truck.png"

_PART_NAMES_AR = {
    "P011": "غطاء المحرك",
    "P021": "الجناح الأمامي (يسار)",
    "P022": "الجناح الأمامي (يمين)",
    "P031": "الباب الأمامي (يسار)",
    "P032": "الباب الأمامي (يمين)",
    "P033": "الباب الخلفي (يسار)",
    "P034": "الباب الخلفي (يمين)",
    "P041": "الصندوق الخلفي",
    "P051": "حامل الرادياتير",
    "P061": "اللوح الخلفي (يسار)",
    "P062": "اللوح الخلفي (يمين)",
    "P081": "عتبة الباب (يسار)",
    "P082": "عتبة الباب (يمين)",
    "P091": "إطار الزجاج الأمامي",
    "P111": "العمود A (يسار)",
    "P112": "العمود A (يمين)",
    "P121": "العمود B (يسار)",
    "P122": "العمود B (يمين)",
    "P123": "العمود C (يسار)",
    "P124": "العمود C (يمين)",
    "P131": "عارضة الجانب (يسار أمام)",
    "P132": "عارضة الجانب (يمين أمام)",
    "P133": "عارضة الجانب (يسار خلف)",
    "P134": "عارضة الجانب (يمين خلف)",
    "P141": "أرضية أمامية",
    "P142": "أرضية خلفية",
    "P144": "عارضة العجلة الخلفية (يمين)",
    "P151": "لوح السقف",
    "P171": "الأرضية الخلفية",
    "P181": "أرضية الصندوق",
}

_PART_POSITIONS = {
    "P011": (50, 14), "P021": (17, 27), "P022": (83, 27),
    "P031": (17, 41), "P032": (83, 41), "P033": (17, 54),
    "P034": (83, 54), "P041": (50, 87), "P051": (50, 19),
    "P061": (17, 67), "P062": (83, 67), "P081": (17, 61),
    "P082": (83, 61), "P091": (50, 22), "P111": (17, 45),
    "P112": (83, 45), "P121": (17, 32), "P122": (83, 32),
    "P123": (17, 65), "P124": (83, 65), "P131": (11, 36),
    "P132": (89, 36), "P133": (11, 63), "P134": (89, 63),
    "P141": (17, 36), "P142": (17, 50), "P144": (83, 36),
    "P151": (50, 30), "P171": (50, 82), "P181": (50, 90),
}
_STATUS_LABEL = {
    "X": "Exchange / تغيير", "W": "Sheet Metal / رش",
    "C": "Corrosion / صدأ",  "A": "Scratches / خدش",
    "U": "Uneven / انبعاج",  "T": "Impairment / تلف",
}
_RANK_LABEL = {"RANK_ONE": "Rank 1", "RANK_TWO": "Rank 2"}
_INNER_STATUS = {
    "1":  ("ok",  "Normal / طبيعي"),    "2":  ("ok",  "Adequate / مناسب"),
    "3":  ("ok",  "None / لا يوجد"),    "4":  ("bad", "Minor Leak / تسرب طفيف"),
    "5":  ("bad", "Leak / تسرب"),        "6":  ("bad", "Minor Oil Leak / تسرب زيت طفيف"),
    "7":  ("bad", "Oil Leak / تسرب زيت"), "8": ("bad", "Low / منخفض"),
    "9":  ("bad", "Excess / زائد"),      "10": ("bad", "Fault / عطل"),
    "11": ("bad", "Present / موجود"),
}
_SECTION_LABEL = {
    "S00": ("Self-diagnosis", "التشخيص الذاتي"),
    "S01": ("Engine",         "المحرك"),
    "S02": ("Transmission",   "ناقل الحركة"),
    "S03": ("Power Transfer", "نقل القوة"),
    "S04": ("Steering",       "التوجيه"),
    "S05": ("Brakes",         "الفرامل"),
    "S06": ("Electrical",     "الكهرباء"),
    "S07": ("Fuel System",    "نظام الوقود"),
}


def _build_inspection_context(extra):
    """Return a dict of pre-rendered HTML strings for the inspection diagrams.
    Safe to call from any view — pure function, no DB access."""
    outers_data = extra.get("outers", [])
    inners_data = extra.get("inners", [])
    images_data = extra.get("images", [])

    # ── outer panel badges & table ────────────────────────────────────────────
    outer_badge_divs = []
    structural_badge_divs = []
    table_rows = []
    for item in outers_data:
        code     = item.get("type", {}).get("code", "")
        name     = _PART_NAMES_AR.get(code) or item.get("type", {}).get("title", code)
        statuses = item.get("statusTypes", [])
        attrs    = item.get("attributes", [])
        rank     = attrs[0] if attrs else ""
        is_structural = code.startswith("P1")
        for st in statuses:
            sc  = st["code"]
            tip = f"{name} · {_STATUS_LABEL.get(sc, sc)}"
            pos = _PART_POSITIONS.get(code)
            if pos:
                left, top = pos
                badge_html = (
                    f'<div class="insp-badge {sc}" style="left:{left}%;top:{top}%" '
                    f'data-tip="{tip}">{sc}</div>'
                )
                if is_structural:
                    structural_badge_divs.append(badge_html)
                else:
                    outer_badge_divs.append(badge_html)
            rank_lbl = _RANK_LABEL.get(rank, rank)
            rank_cls = "insp-rank-1" if rank == "RANK_ONE" else "insp-rank-2"
            table_rows.append(
                f'<tr><td>{name}</td>'
                f'<td><span class="insp-lb {sc}">{sc}</span> {_STATUS_LABEL.get(sc, sc)}</td>'
                f'<td><span class="insp-rank {rank_cls}">{rank_lbl}</span></td></tr>'
            )

    # ── inner mechanical sections ─────────────────────────────────────────────
    inner_sections_html = []
    for section in inners_data:
        sec_code = section.get("type", {}).get("code", "")
        sec_en, sec_ar = _SECTION_LABEL.get(sec_code, (section.get("type", {}).get("title", sec_code), ""))
        rows = []

        def _walk(children):
            for child in children:
                st = child.get("statusType")
                if st and st.get("code"):
                    cls, lbl = _INNER_STATUS.get(str(st["code"]), ("", st.get("title", "")))
                    rows.append(
                        f'<div class="insp-check-row">'
                        f'<span class="insp-check-lbl">{child.get("type", {}).get("title", "")}</span>'
                        f'<span class="insp-chip {cls}">{lbl}</span>'
                        f'</div>'
                    )
                if child.get("children"):
                    _walk(child["children"])

        _walk(section.get("children", []))
        if rows:
            inner_sections_html.append(
                f'<div class="insp-section">'
                f'<div class="insp-section-title">{sec_en}'
                f' <span class="insp-section-ar">/ {sec_ar}</span></div>'
                f'<div class="insp-checklist">{"".join(rows)}</div>'
                f'</div>'
            )

    # ── inspection report images (scanned pages) ──────────────────────────────
    insp_images = [
        _ENCAR_BASE_IMG + img["path"]
        for img in images_data
        if isinstance(img, dict) and img.get("path")
    ]

    damage_count = sum(len(i.get("statusTypes", [])) for i in outers_data)

    return {
        "outer_badges_html":      "".join(outer_badge_divs),
        "structural_badges_html": "".join(structural_badge_divs),
        "table_rows_html":        "".join(table_rows),
        "inner_html":             "".join(inner_sections_html),
        "insp_images":            insp_images,
        "damage_count":           damage_count,
        "has_outer":              bool(outers_data),
        "has_inspection":         "outers" in extra,
        "has_inner":              bool(inner_sections_html),
        "has_images":             bool(insp_images),
        "sedan_img":              _SEDAN_IMG,
        "truck_img":              _TRUCK_IMG,
    }


def car_report(request, lot_number):
    """
    Generate a dynamic inspection report for a car from the database.
    Mirrors the logic of report_from_csv.py but reads from ApiCar instead of CSV.
    """
    # ── lookup car ────────────────────────────────────────────────────────────
    car = get_object_or_404(ApiCar, lot_number=lot_number)
    vid = lot_number

    # ── static / CDN blueprint image URLs ─────────────────────────────────────
    BASE_IMG  = _ENCAR_BASE_IMG
    SEDAN_IMG = _SEDAN_IMG
    TRUCK_IMG = _TRUCK_IMG

    # ── part positions for damage badges ──────────────────────────────────────
    PART_POSITIONS = _PART_POSITIONS
    STATUS_LABEL   = {k: v.split(" / ")[0] + " (" + v.split(" / ")[-1] + ")" if " / " in v else v for k, v in _STATUS_LABEL.items()}
    RANK_LABEL     = _RANK_LABEL
    INNER_STATUS   = _INNER_STATUS
    SECTION_LABEL  = _SECTION_LABEL
    OPTION_NAMES = {
        "001": ("ABS", "نظام منع انغلاق المكابح"),
        "003": ("Airbag (Driver)", "وسادة هوائية (السائق)"),
        "004": ("Airbag (Passenger)", "وسادة هوائية (الراكب)"),
        "005": ("Side Airbag", "وسادة هوائية جانبية"),
        "006": ("Curtain Airbag", "وسادة هوائية ستائرية"),
        "007": ("Knee Airbag", "وسادة هوائية للركبة"),
        "009": ("Lane Keeping Assist", "مساعد الحفاظ على المسار"),
        "010": ("Blind Spot Monitor", "مراقبة النقطة العمياء"),
        "011": ("Rear Cross-Traffic Alert", "تنبيه حركة المرور الخلفية"),
        "012": ("Forward Collision Warning", "تحذير الاصطدام الأمامي"),
        "013": ("Autonomous Emergency Braking", "الفرمل الطارئ التلقائي"),
        "014": ("ESC (Stability Control)", "نظام التحكم في الثبات"),
        "015": ("Traction Control", "التحكم في الجر"),
        "017": ("Tire Pressure Monitoring", "مراقبة ضغط الإطارات"),
        "019": ("Parking Sensors (Front)", "حساسات الركن (أمامية)"),
        "020": ("Parking Sensors (Rear)", "حساسات الركن (خلفية)"),
        "021": ("Around View Monitor", "كاميرا 360 درجة"),
        "022": ("Backup Camera", "كاميرا الرجوع للخلف"),
        "023": ("Cruise Control", "مثبت السرعة"),
        "024": ("Adaptive Cruise Control", "مثبت السرعة التكيفي"),
        "025": ("Auto Parking", "الركن التلقائي"),
        "026": ("Power Trunk", "صندوق خلفي كهربائي"),
        "027": ("Smart Key / Keyless Entry", "مفتاح ذكي / دخول بدون مفتاح"),
        "029": ("Push-Button Start", "تشغيل بضغطة زر"),
        "030": ("Sunroof", "فتحة سقف"),
        "031": ("Panoramic Sunroof", "فتحة سقف بانورامية"),
        "034": ("Electric Parking Brake", "فرامل انتظار كهربائية"),
        "035": ("Auto Hold", "تثبيت تلقائي"),
        "036": ("Electric Folding Mirrors", "مرايا طي كهربائية"),
        "037": ("Heated Mirrors", "مرايا مُدفَّأة"),
        "039": ("Power Seats (Driver)", "مقعد كهربائي (السائق)"),
        "040": ("Power Seats (Passenger)", "مقعد كهربائي (الراكب)"),
        "041": ("Heated Seats (Front)", "مقاعد دافئة (أمامية)"),
        "042": ("Heated Seats (Rear)", "مقاعد دافئة (خلفية)"),
        "043": ("Ventilated Seats (Front)", "مقاعد مُهوَّأة (أمامية)"),
        "044": ("Ventilated Seats (Rear)", "مقاعد مُهوَّأة (خلفية)"),
        "045": ("Massage Seats", "مقاعد مساج"),
        "046": ("Heated Steering Wheel", "مقود مُدفَّأ"),
        "049": ("Head-Up Display", "شاشة عرض أمامية"),
        "051": ("Dual-Zone Climate Control", "تحكم مناخي ثنائي المنطقة"),
        "052": ("Rear Climate Control", "تحكم مناخي خلفي"),
        "055": ("Navigation System", "نظام الملاحة"),
        "056": ("Apple CarPlay / Android Auto", "Apple CarPlay / Android Auto"),
        "057": ("Bluetooth", "بلوتوث"),
        "059": ("Wireless Charging", "شحن لاسلكي"),
        "060": ("Premium Audio", "صوت فاخر"),
        "063": ("Digital Instrument Cluster", "عداد رقمي"),
        "065": ("LED Headlights", "مصابيح LED أمامية"),
        "066": ("LED Daytime Running Lights", "مصابيح LED نهارية"),
        "067": ("LED Taillights", "مصابيح LED خلفية"),
        "068": ("Auto Headlights", "مصابيح تلقائية"),
        "069": ("Adaptive Headlights", "مصابيح تكيفية"),
        "070": ("Fog Lights", "مصابيح الضباب"),
        "071": ("Alloy Wheels", "جنوط سبائك"),
        "072": ('18" Wheels', "جنوط 18 بوصة"),
        "073": ('19" Wheels', "جنوط 19 بوصة"),
        "074": ('20"+ Wheels', "جنوط 20 بوصة أو أكبر"),
        "081": ("Leather Seats", "مقاعد جلدية"),
        "082": ("Leather Interior", "داخلية جلدية"),
        "084": ("3rd Row Seating", "مقاعد الصف الثالث"),
        "085": ("Folding Rear Seats", "مقاعد خلفية قابلة للطي"),
        "088": ("Tinted Windows", "زجاج ملون"),
        "092": ("AWD / 4WD", "دفع رباعي"),
        "094": ("Sport Mode", "وضع الرياضة"),
        "099": ("Turbocharger", "تيربو"),
        "10004": ("Black Box (Dashcam)", "كاميرا لوحة القيادة"),
        "10006": ("PPF (Paint Protection Film)", "فيلم حماية الطلاء"),
        "10007": ("Ceramic Coating", "طلاء سيراميك"),
    }

    # ── helpers ────────────────────────────────────────────────────────────────
    def fmt_date(s):
        if s and len(str(s)) == 8 and str(s).isdigit():
            s = str(s)
            return f"{s[:4]}-{s[4:6]}-{s[6:]}"
        return s or "—"

    def check_chip(val, true_class="ok", false_class="bad", true_label="Normal", false_label="Yes"):
        if val:
            return f'<span class="chip {true_class}">{true_label}</span>'
        return f'<span class="chip {false_class}">{false_label}</span>'

    def extract_inners(inners):
        sections = []
        for section in inners:
            sec_code = section.get("type", {}).get("code", "")
            sec_en, sec_ar = SECTION_LABEL.get(sec_code, (section.get("type", {}).get("title", sec_code), ""))
            rows = []
            def walk(children):
                for child in children:
                    st = child.get("statusType")
                    if st and st.get("code"):
                        cls, lbl = INNER_STATUS.get(str(st["code"]), ("", st.get("title", "")))
                        rows.append((child.get("type", {}).get("title", ""), cls, lbl))
                    if child.get("children"):
                        walk(child["children"])
            walk(section.get("children", []))
            if rows:
                sections.append((sec_en, sec_ar, rows))
        return sections

    def build_outer_badges_and_table(outers):
        outer_badge_divs = []
        structural_badge_divs = []
        table_rows = []
        for item in outers:
            code = item.get("type", {}).get("code", "")
            name = _PART_NAMES_AR.get(code) or item.get("type", {}).get("title", code)
            statuses = item.get("statusTypes", [])
            attrs = item.get("attributes", [])
            rank = attrs[0] if attrs else ""
            is_structural = code.startswith("P1")
            for st in statuses:
                sc = st["code"]
                tip = f"{name} · {STATUS_LABEL.get(sc, sc)}"
                pos = PART_POSITIONS.get(code)
                if pos:
                    left, top = pos
                    badge_html = (
                        f'<div class="badge {sc}" style="left:{left}%;top:{top}%" '
                        f'data-tip="{tip}">{sc}</div>'
                    )
                    if is_structural:
                        structural_badge_divs.append(badge_html)
                    else:
                        outer_badge_divs.append(badge_html)
                rank_lbl = RANK_LABEL.get(rank, rank)
                rank_cls = "rank-1" if rank == "RANK_ONE" else "rank-2"
                table_rows.append(f"""
        <tr>
          <td>{name}</td>
          <td><span class="lb {sc}" style="display:inline-flex">{sc}</span>&nbsp; {STATUS_LABEL.get(sc, sc)}</td>
          <td><span class="rank-badge {rank_cls}">{rank_lbl}</span></td>
          <td>{code}</td>
        </tr>""")
        return outer_badge_divs, structural_badge_divs, table_rows

    # ── extract data from DB fields ───────────────────────────────────────────
    mark         = car.manufacturer.name if car.manufacturer else ""
    model_name   = car.model.name if car.model else ""
    badge_name   = car.badge.name if car.badge else ""
    year         = car.year or ""
    color        = car.color.name if car.color else ""
    price        = car.price or 0
    mileage      = car.mileage or 0
    engine_type  = car.fuel or ""
    trans_type   = car.transmission or ""
    body_type    = car.body.name if car.body else ""
    address      = car.address or ""
    try:
        displacement = int(car.engine.replace("cc", "").replace(",", "").strip()) if car.engine else 0
    except (ValueError, AttributeError):
        displacement = 0

    extra        = car.extra_features or {}
    record_data  = extra.get("record") or {}
    options_raw  = car.options or {}
    images_raw   = car.images or []

    title    = f"{mark} {model_name}"
    sub_parts = [p for p in [badge_name, str(year), f"ID {vid}"] if p]
    subtitle = " · ".join(sub_parts)

    # ── photos ────────────────────────────────────────────────────────────────
    import json as _json
    def _photo_entry(p):
        if isinstance(p, str):
            return {"code": "", "type": "OUTER", "url": p}
        return {"code": p.get("code", ""), "type": p.get("type", "OUTER"), "url": BASE_IMG + p.get("path", "")}
    photo_js = _json.dumps([_photo_entry(p) for p in images_raw])
    if images_raw:
        first = images_raw[0]
        first_photo_url = first if isinstance(first, str) else BASE_IMG + first.get("path", "")
    else:
        first_photo_url = ""

    # ── options ───────────────────────────────────────────────────────────────
    all_opt_codes = (
        list(options_raw.get("standard", []))
        + list(options_raw.get("choice", []))
        + list(options_raw.get("etc", []))
    )
    named_opts   = [OPTION_NAMES[c] for c in all_opt_codes if c in OPTION_NAMES]
    unknown_opts = [c for c in all_opt_codes if c not in OPTION_NAMES]
    options_html = "".join(
        f'<span class="opt-tag"><span class="opt-en">{en}</span><span class="opt-ar">{ar}</span></span>'
        for en, ar in named_opts
    )
    if unknown_opts:
        options_html += "".join(f'<span class="opt-tag opt-unknown">Code {c}</span>' for c in unknown_opts)
    if not options_html:
        options_html = '<span style="color:#bbb;font-size:12px">No options data available</span>'

    # ── inspection data ────────────────────────────────────────────────────────
    master      = extra.get("master", {})
    detail      = (master.get("detail") or {})
    outers_data = extra.get("outers", [])
    inners_data = extra.get("inners", [])
    insp_images = [
        BASE_IMG + img["path"]
        for img in extra.get("images", [])
        if isinstance(img, dict) and img.get("path")
    ]

    record_no  = detail.get("recordNo", "—")
    issue_date = fmt_date(detail.get("issueDate"))
    valid_end  = fmt_date(detail.get("validityEndDate"))
    first_reg  = fmt_date(detail.get("firstRegistrationDate"))
    vin        = car.vin or detail.get("vin", "—")
    insp_km    = detail.get("mileage") or mileage
    co         = detail.get("coout", "—")
    hc         = detail.get("hcout", "—")
    engine_ok  = detail.get("engineCheck", "N") == "Y"
    trans_ok   = detail.get("trnsCheck",   "N") == "Y"
    waterlog   = detail.get("waterlog", False)
    tuning     = detail.get("tuning", False)
    simple_rep = master.get("simpleRepair", False)
    accident   = master.get("accdient", False)
    usage_types = detail.get("usageChangeTypes", [])
    usage_str  = ", ".join(u.get("title", "") for u in usage_types) if usage_types else "None"
    guarantee_type = detail.get("guarantyType") or {}
    guarantee  = guarantee_type.get("title", "—") if isinstance(guarantee_type, dict) else "—"

    # ── outer panel badges & table ─────────────────────────────────────────────
    outer_badge_divs, structural_badge_divs, table_rows = build_outer_badges_and_table(outers_data)
    outer_badges_html      = "\n          ".join(outer_badge_divs)
    structural_badges_html = "\n          ".join(structural_badge_divs)
    damage_count = sum(len(i.get("statusTypes", [])) for i in outers_data)
    table_rows_html = "".join(table_rows) if table_rows else (
        '<tr><td colspan="4" style="color:#aaa;text-align:center">No outer panel damage recorded</td></tr>'
    )

    # ── inner mechanical checklist ─────────────────────────────────────────────
    inner_sections = extract_inners(inners_data)
    inner_html_parts = []
    for sec_en, sec_ar, rows in inner_sections:
        rows_html = "".join(
            f'<div class="check-row"><span class="lbl">{name}</span>'
            f'<span class="chip {cls}">{lbl}</span></div>'
            for name, cls, lbl in rows
        )
        inner_html_parts.append(
            f'<div class="inner-section">'
            f'<div class="inner-section-title">{sec_en}'
            f' <span dir="rtl" style="font-weight:400;color:#bbb;font-size:10px">/ {sec_ar}</span></div>'
            f'<div class="checklist">{rows_html}</div>'
            f'</div>'
        )
    inner_html = "\n".join(inner_html_parts) if inner_html_parts else (
        '<p style="color:#aaa;padding:20px;text-align:center">No mechanical inspection data available</p>'
    )

    legend_html = (
        '<div class="legend">'
        '<div class="leg"><span class="lb X">X</span> Exchange / Replacement</div>'
        '<div class="leg"><span class="lb W">W</span> Sheet Metal / Welding</div>'
        '<div class="leg"><span class="lb C">C</span> Corrosion / Rust</div>'
        '<div class="leg"><span class="lb A">A</span> Scratches</div>'
        '<div class="leg"><span class="lb U">U</span> Uneven Surface</div>'
        '<div class="leg"><span class="lb T">T</span> Impairment</div>'
        '</div>'
    )

    # ── insurance / record data ────────────────────────────────────────────────
    def _fmt_insurance_val(v):
        if v is None or v == "":
            return "—"
        if isinstance(v, bool):
            return "Yes" if v else "No"
        if isinstance(v, (int, float)):
            return f"{v:,}"
        return str(v)

    def _build_insurance_html(rec):
        if not rec or not isinstance(rec, dict):
            return '<p style="color:#aaa;padding:20px;text-align:center">No insurance data available</p>'

        # Known field labels (en / ar)
        LABELS = {
            "insuranceCompany":     ("Insurance Company",  "شركة التأمين"),
            "insuranceType":        ("Insurance Type",     "نوع التأمين"),
            "insuranceStartDate":   ("Start Date",         "تاريخ البدء"),
            "insuranceEndDate":     ("End Date",           "تاريخ الانتهاء"),
            "accidentCount":        ("Accident Count",     "عدد الحوادث"),
            "totalLossAmount":      ("Total Loss Amount",  "إجمالي الخسارة"),
            "myAccidentCount":      ("My Accident Count",  "حوادثي"),
            "otherAccidentCount":   ("Other Accident Count","حوادث الطرف الآخر"),
            "myAccidentAmount":     ("My Accident Amount", "مبلغ حوادثي"),
            "otherAccidentAmount":  ("Other Accident Amount","مبلغ الطرف الآخر"),
            "ownerChangeCount":     ("Ownership Changes",  "تغييرات الملكية"),
            "carNo":                ("Car Number",         "رقم السيارة"),
            "carType":              ("Car Type",           "نوع السيارة"),
        }
        rows = []
        # Render known fields first in order
        for key, (en, ar) in LABELS.items():
            if key in rec:
                rows.append(
                    f'<div class="check-row">'
                    f'<span class="lbl bil"><span class="bil-en">{en}</span><span class="bil-ar">{ar}</span></span>'
                    f'<span>{_fmt_insurance_val(rec[key])}</span>'
                    f'</div>'
                )
        # Render any remaining unknown keys
        known_keys = set(LABELS.keys())
        for key, val in rec.items():
            if key not in known_keys and not isinstance(val, (dict, list)):
                rows.append(
                    f'<div class="check-row">'
                    f'<span class="lbl">{key}</span>'
                    f'<span>{_fmt_insurance_val(val)}</span>'
                    f'</div>'
                )
        if not rows:
            return '<p style="color:#aaa;padding:20px;text-align:center">No insurance data available</p>'
        return '<div class="checklist">' + "".join(rows) + '</div>'

    insurance_html = _build_insurance_html(record_data)

    # ── render HTML ────────────────────────────────────────────────────────────
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>{title} – Encar Report</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --blue:   #1e88e5;
      --red:    #e53935;
      --orange: #fb8c00;
      --green:  #43a047;
      --bg:     #f0f2f5;
      --card:   #fff;
      --radius: 12px;
    }}
    body {{ background: var(--bg); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; color: #222; min-height: 100vh; }}
    nav {{ position: sticky; top: 0; z-index: 100; background: #fff; border-bottom: 1px solid #e0e0e0; display: flex; align-items: center; padding: 0 24px; }}
    .nav-brand {{ font-size: 15px; font-weight: 700; color: #111; padding: 16px 0; margin-right: 32px; letter-spacing: -.3px; }}
    .nav-brand span {{ color: var(--blue); }}
    .tab {{ padding: 18px 20px; font-size: 13.5px; font-weight: 500; color: #888; cursor: pointer; border-bottom: 3px solid transparent; user-select: none; transition: color .2s, border-color .2s; }}
    .tab.active {{ color: #111; border-color: #111; }}
    .tab:hover:not(.active) {{ color: #444; }}
    .page {{ display: none; padding: 28px 24px 60px; max-width: 900px; margin: 0 auto; }}
    .page.active {{ display: block; }}
    .section-title {{ font-size: 11.5px; font-weight: 700; letter-spacing: .8px; text-transform: uppercase; color: #999; margin: 28px 0 10px; }}
    .section-title:first-child {{ margin-top: 0; }}
    .card {{ background: var(--card); border-radius: var(--radius); box-shadow: 0 1px 6px #0001, 0 2px 16px #0001; overflow: hidden; margin-bottom: 18px; }}
    .hero {{ display: flex; gap: 20px; padding: 20px; }}
    .hero-photo {{ width: 200px; height: 140px; object-fit: cover; border-radius: 8px; flex-shrink: 0; background: #eee; }}
    .hero-info {{ flex: 1; }}
    .hero-info h1 {{ font-size: 20px; font-weight: 700; line-height: 1.3; }}
    .hero-info .sub {{ font-size: 12.5px; color: #888; margin-top: 3px; }}
    .hero-price {{ font-size: 28px; font-weight: 800; color: var(--blue); margin-top: 12px; }}
    .hero-price span {{ font-size: 14px; color: #999; font-weight: 400; }}
    .tag-row {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }}
    .tag {{ padding: 4px 10px; border-radius: 20px; font-size: 11.5px; font-weight: 600; background: #f0f2f5; color: #555; }}
    .tag.accent {{ background: #e3f0fd; color: var(--blue); }}
    .spec-grid {{ display: grid; grid-template-columns: repeat(3,1fr); border-top: 1px solid #f2f2f2; }}
    .spec-cell {{ padding: 14px 18px; border-right: 1px solid #f2f2f2; }}
    .spec-cell:nth-child(3n) {{ border-right: none; }}
    .spec-cell .label {{ font-size: 10.5px; color: #aaa; text-transform: uppercase; letter-spacing: .5px; }}
    .spec-cell .value {{ font-size: 14px; font-weight: 600; margin-top: 3px; }}
    .history-row {{ display: grid; grid-template-columns: repeat(4,1fr); padding: 18px 20px; gap: 8px; }}
    .hist-item {{ text-align: center; }}
    .hist-item .h-val {{ font-size: 26px; font-weight: 800; }}
    .hist-item .h-val.danger {{ color: var(--red); }}
    .hist-item .h-val.ok    {{ color: var(--green); }}
    .hist-item .h-lab  {{ font-size: 11px; color: #aaa; margin-top: 2px; }}
    .checklist {{ display: grid; grid-template-columns: 1fr 1fr; }}
    .check-row {{ display: flex; align-items: center; justify-content: space-between; padding: 9px 18px; border-bottom: 1px solid #f8f8f8; font-size: 12.5px; }}
    .check-row:nth-child(odd) {{ border-right: 1px solid #f8f8f8; }}
    .check-row .lbl {{ color: #666; }}
    .chip {{ padding: 2px 10px; border-radius: 10px; font-size: 11px; font-weight: 600; }}
    .chip.ok  {{ background: #e8f5e9; color: #2e7d32; }}
    .chip.bad {{ background: #fce4e4; color: #c62828; }}
    .gallery-tabs {{ display: flex; padding: 0 16px; border-bottom: 1px solid #f2f2f2; }}
    .gtab {{ padding: 10px 14px; font-size: 12px; font-weight: 600; color: #aaa; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; }}
    .gtab.on {{ color: #111; border-color: #111; }}
    .gallery {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(130px,1fr)); gap: 8px; padding: 16px; }}
    .gallery img {{ width: 100%; aspect-ratio: 4/3; object-fit: cover; border-radius: 6px; background: #eee; cursor: zoom-in; transition: opacity .2s; }}
    .gallery img:hover {{ opacity: .82; }}
    #lb {{ display: none; position: fixed; inset: 0; z-index: 999; background: #000c; align-items: center; justify-content: center; }}
    #lb.on {{ display: flex; }}
    #lb img {{ max-width: 92vw; max-height: 88vh; border-radius: 8px; }}
    #lb-close {{ position: absolute; top: 18px; right: 22px; font-size: 30px; color: #fff; cursor: pointer; }}
    .diagram {{ position: relative; width: 100%; user-select: none; }}
    .diagram img {{ width: 100%; display: block; }}
    .badge {{ position: absolute; width: 5.5%; aspect-ratio: 1/1; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.5vw; font-weight: 800; color: #fff; transform: translate(-50%,-50%); box-shadow: 0 3px 8px #0004; cursor: default; transition: transform .15s, box-shadow .15s; }}
    .badge:hover {{ transform: translate(-50%,-50%) scale(1.25); box-shadow: 0 5px 14px #0005; }}
    .badge.X {{ background: var(--red); }}
    .badge.W {{ background: var(--blue); }}
    .badge.C {{ background: var(--orange); }}
    .badge.A {{ background: #7cb9e8; }}
    .badge.U {{ background: #6d7c47; }}
    .badge.T {{ background: #9e9e9e; }}
    .badge::after {{ content: attr(data-tip); position: absolute; bottom: 120%; left: 50%; transform: translateX(-50%) scale(.9); background: #222; color: #fff; font-size: 11px; font-weight: 500; white-space: nowrap; padding: 5px 9px; border-radius: 5px; pointer-events: none; opacity: 0; transition: opacity .15s, transform .15s; }}
    .badge:hover::after {{ opacity: 1; transform: translateX(-50%) scale(1); }}
    .legend {{ display: flex; flex-wrap: wrap; gap: 16px; padding: 14px 20px; border-top: 1px solid #f5f5f5; }}
    .leg {{ display: flex; align-items: center; gap: 6px; font-size: 12px; color: #555; }}
    .lb {{ width: 22px; height: 22px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 800; color: #fff; flex-shrink: 0; }}
    .lb.X {{ background: var(--red); }}
    .lb.W {{ background: var(--blue); }}
    .lb.C {{ background: var(--orange); }}
    .lb.A {{ background: #7cb9e8; }}
    .lb.U {{ background: #6d7c47; }}
    .lb.T {{ background: #9e9e9e; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
    th {{ background: #fafafa; padding: 9px 16px; text-align: left; color: #888; font-size: 11px; font-weight: 600; letter-spacing: .4px; text-transform: uppercase; border-bottom: 1px solid #f0f0f0; }}
    td {{ padding: 10px 16px; border-bottom: 1px solid #f8f8f8; }}
    tr:last-child td {{ border-bottom: none; }}
    .rank-badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 10.5px; font-weight: 600; }}
    .rank-1 {{ background: #fce4e4; color: #c62828; }}
    .rank-2 {{ background: #fff3e0; color: #e65100; }}
    .insp-header {{ padding: 16px 20px; border-bottom: 1px solid #f5f5f5; }}
    .insp-header h3 {{ font-size: 14px; font-weight: 700; }}
    .insp-header p  {{ font-size: 12px; color: #aaa; margin-top: 3px; }}
    .insp-sub-title {{ font-size: 11px; font-weight: 700; letter-spacing: .6px; text-transform: uppercase; color: #aaa; padding: 14px 20px 8px; border-top: 1px solid #f2f2f2; }}
    .inner-section {{ border-bottom: 1px solid #f5f5f5; }}
    .inner-section:last-child {{ border-bottom: none; }}
    .inner-section-title {{ font-size: 11px; font-weight: 700; letter-spacing: .6px; text-transform: uppercase; color: #aaa; padding: 10px 18px 6px; }}
    .foot-note {{ font-size: 11px; color: #bbb; text-align: center; margin-top: 20px; }}
    .options-wrap {{ display: flex; flex-wrap: wrap; gap: 7px; padding: 16px 18px; }}
    .opt-tag {{ padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: 500; background: #f0f4ff; color: #1e4db7; border: 1px solid #d0dcff; display: flex; flex-direction: column; align-items: center; gap: 1px; }}
    .opt-tag.opt-unknown {{ background: #f5f5f5; color: #999; border-color: #e0e0e0; }}
    .opt-en {{ font-size: 11.5px; font-weight: 600; }}
    .opt-ar {{ font-size: 10.5px; font-weight: 400; color: #4a6fa5; direction: rtl; }}
    .bil {{ display: flex; flex-direction: column; line-height: 1.2; }}
    .bil-en {{ font-size: 12.5px; color: #666; }}
    .bil-ar {{ font-size: 11px; color: #aaa; direction: rtl; text-align: right; }}
    .meta-row {{ display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 18px 14px; border-top: 1px solid #f5f5f5; }}
    .meta-tag {{ font-size: 11px; color: #999; background: #f7f7f7; border-radius: 4px; padding: 2px 8px; }}
  </style>
</head>
<body>

<nav>
  <div class="nav-brand"><span>Encar</span> Report</div>
  <div class="tab active" onclick="switchPage('details',this)">Details &amp; Photos / <span dir="rtl" style="font-size:12px">التفاصيل والصور</span></div>
  <div class="tab"        onclick="switchPage('inspection',this)">Inspection / <span dir="rtl" style="font-size:12px">الفحص</span></div>
</nav>

<!-- PAGE 1 -->
<div id="page-details" class="page active">

  <div class="section-title">Vehicle Overview</div>
  <div class="card">
    <div class="hero">
      <img class="hero-photo" id="hero-img"
           src="{first_photo_url}"
           alt="{title}"
           onerror="this.style.background='#ddd';this.removeAttribute('src')">
      <div class="hero-info">
        <h1>{title}</h1>
        <div class="sub">{subtitle}</div>
        <div class="hero-price">{"&#x20A9;{:,}".format(price) if price else "—"}<span>만원</span></div>
        <div class="tag-row">
          <span class="tag">{engine_type}</span>
          <span class="tag">{trans_type}</span>
          <span class="tag">{body_type}</span>
          <span class="tag">{color}</span>
        </div>
      </div>
    </div>
    <div class="spec-grid">
      <div class="spec-cell"><div class="label">Mileage / <span dir="rtl">المسافة</span></div><div class="value">{mileage:,} km</div></div>
      <div class="spec-cell"><div class="label">Engine / <span dir="rtl">المحرك</span></div><div class="value">{f"{displacement:,} cc" if displacement else engine_type}</div></div>
      <div class="spec-cell"><div class="label">First Reg. / <span dir="rtl">أول تسجيل</span></div><div class="value">{first_reg or year}</div></div>
      <div class="spec-cell"><div class="label">Fuel / <span dir="rtl">الوقود</span></div><div class="value">{engine_type}</div></div>
      <div class="spec-cell"><div class="label">Transmission / <span dir="rtl">ناقل الحركة</span></div><div class="value">{trans_type}</div></div>
      <div class="spec-cell"><div class="label">Year / <span dir="rtl">الموديل</span></div><div class="value">{year}</div></div>
    </div>
    {"<div class='meta-row'><span class='meta-tag'>📍 " + address + "</span></div>" if address else ""}
  </div>

  <div class="section-title">Quick Check</div>
  <div class="card">
    <div class="checklist">
      <div class="check-row"><span class="lbl bil"><span class="bil-en">Engine</span><span class="bil-ar">المحرك</span></span>{check_chip(engine_ok, true_label="Pass", false_label="Fail")}</div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">Transmission</span><span class="bil-ar">ناقل الحركة</span></span>{check_chip(trans_ok, true_label="Pass", false_label="Fail")}</div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">Accident record</span><span class="bil-ar">سجل الحوادث</span></span>{check_chip(not accident, false_class="ok", true_class="bad", true_label="None", false_label="Yes")}</div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">Simple repair</span><span class="bil-ar">إصلاح بسيط</span></span>{check_chip(not simple_rep, false_class="ok", true_class="bad", true_label="None", false_label="Yes")}</div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">Tuning</span><span class="bil-ar">تعديل</span></span>{check_chip(not tuning, false_class="ok", true_class="bad", true_label="None", false_label="Yes")}</div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">Flood damage</span><span class="bil-ar">تضرر من الفيضان</span></span>{check_chip(not waterlog, false_class="ok", true_class="bad", true_label="None", false_label="Yes")}</div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">Usage history</span><span class="bil-ar">تاريخ الاستخدام</span></span><span>{usage_str}</span></div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">Guarantee</span><span class="bil-ar">الضمان</span></span><span>{guarantee}</span></div>
    </div>
  </div>

  <div class="section-title">Options</div>
  <div class="card">
    <div class="options-wrap">
      {options_html}
    </div>
  </div>

  <div class="section-title">Photos</div>
  <div class="card">
    <div class="gallery-tabs">
      <div class="gtab on" onclick="filterGallery('ALL',this)">All</div>
      <div class="gtab"    onclick="filterGallery('OUTER',this)">Exterior</div>
      <div class="gtab"    onclick="filterGallery('INNER',this)">Interior</div>
      <div class="gtab"    onclick="filterGallery('OPTION',this)">Options</div>
    </div>
    <div class="gallery" id="gallery"></div>
  </div>

  <p class="foot-note">Source: DB · Vehicle {vid} · {title}</p>
</div>


<!-- PAGE 2 -->
<div id="page-inspection" class="page">

  <div class="section-title">Outer Panel Damage Map</div>
  <div class="card">
    <div class="insp-header">
      <h3>Outer Panel — {damage_count} damage item{"s" if damage_count != 1 else ""} recorded</h3>
      <p>Record {record_no} · Issued {issue_date} · Valid until {valid_end}</p>
    </div>

    <div class="insp-sub-title">Outer Panel / <span dir="rtl" style="font-weight:400">الهيكل الخارجي</span></div>
    <div class="diagram">
      <img src="{SEDAN_IMG}" alt="Outer panel blueprint">
      {outer_badges_html}
    </div>
    {legend_html if outer_badge_divs else '<p style="color:#aaa;padding:20px;text-align:center">No outer body panel damage recorded</p>'}

    <div class="insp-sub-title">Structural / <span dir="rtl" style="font-weight:400">الهيكل الهيكلي</span></div>
    <div class="diagram">
      <img src="{TRUCK_IMG}" alt="Structural blueprint">
      {structural_badges_html}
    </div>
    {legend_html if structural_badge_divs else '<p style="color:#aaa;padding:20px;text-align:center">No structural / underbody damage recorded</p>'}

    <div class="insp-sub-title">Mechanical / <span dir="rtl" style="font-weight:400">الفحص الميكانيكي</span></div>
    {inner_html}
  </div>

  <div class="section-title">Damage Details</div>
  <div class="card">
    <table>
      <thead><tr><th>Part</th><th>Status</th><th>Rank</th><th>Code</th></tr></thead>
      <tbody>{table_rows_html}</tbody>
    </table>
  </div>

  <div class="section-title">Inspection Record</div>
  <div class="card">
    <div class="checklist">
      <div class="check-row"><span class="lbl bil"><span class="bil-en">Record No.</span><span class="bil-ar">رقم السجل</span></span><span>{record_no}</span></div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">Issue Date</span><span class="bil-ar">تاريخ الإصدار</span></span><span>{issue_date}</span></div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">Valid Until</span><span class="bil-ar">صالح حتى</span></span><span>{valid_end}</span></div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">First Reg. Date</span><span class="bil-ar">تاريخ أول تسجيل</span></span><span>{first_reg}</span></div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">VIN</span><span class="bil-ar">رقم الهيكل</span></span><span style="font-size:11px">{vin}</span></div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">Model Year</span><span class="bil-ar">سنة الصنع</span></span><span>{year}</span></div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">Mileage at Inspection</span><span class="bil-ar">المسافة عند الفحص</span></span><span>{insp_km:,} km</span></div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">CO Emission</span><span class="bil-ar">انبعاثات CO</span></span><span>{co}</span></div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">HC Emission</span><span class="bil-ar">انبعاثات HC</span></span><span>{hc}</span></div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">Guarantee Type</span><span class="bil-ar">نوع الضمان</span></span><span>{guarantee}</span></div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">Engine Check</span><span class="bil-ar">فحص المحرك</span></span>{check_chip(engine_ok, true_label="Pass", false_label="Fail")}</div>
      <div class="check-row"><span class="lbl bil"><span class="bil-en">Transmission Check</span><span class="bil-ar">فحص ناقل الحركة</span></span>{check_chip(trans_ok, true_label="Pass", false_label="Fail")}</div>
    </div>
  </div>

  <div class="section-title">Insurance / <span dir="rtl" style="font-weight:400">بيانات التأمين</span></div>
  <div class="card">
    {insurance_html}
  </div>

  <p class="foot-note">Hover badges to see part details · Source: DB · Vehicle {vid}</p>
</div>

<!-- LIGHTBOX -->
<div id="lb" onclick="closeLb()">
  <span id="lb-close">&times;</span>
  <img id="lb-img" src="" alt="">
</div>

<script>
  function switchPage(id, el) {{
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById('page-' + id).classList.add('active');
    el.classList.add('active');
  }}

  const photos = {photo_js};
  let currentFilter = 'ALL';

  function filterGallery(type, el) {{
    currentFilter = type;
    document.querySelectorAll('.gtab').forEach(t => t.classList.remove('on'));
    el.classList.add('on');
    renderGallery();
  }}

  function renderGallery() {{
    const list = currentFilter === 'ALL' ? photos : photos.filter(p => p.type === currentFilter);
    document.getElementById('gallery').innerHTML = list.map(p =>
      `<img src="${{p.url}}" alt="${{p.type}} ${{p.code}}"
            loading="lazy" onerror="this.style.display='none'"
            onclick="openLb('${{p.url}}')">`
    ).join('');
  }}

  function openLb(src) {{
    document.getElementById('lb-img').src = src;
    document.getElementById('lb').classList.add('on');
  }}
  function closeLb() {{
    document.getElementById('lb').classList.remove('on');
    document.getElementById('lb-img').src = '';
  }}
  document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeLb(); }});

  renderGallery();
</script>
</body>
</html>"""

    return HttpResponse(html, content_type="text/html; charset=utf-8")


def car_availability_check(request, lot_number):
    """
    Proxy Encar API to check whether a car lot is still available, and
    refresh our stored price when Encar's listing price has changed.

    Returns JSON: { available, price, price_changed }
      available     true|false|null  (200 / 404 / error)
      price         current price in won (or null if unavailable)
      price_changed true if we updated our DB price this call
    """
    try:
        url = (
            f"https://api.encar.com/v1/readside/vehicle/{lot_number}"
            "?include=ADVERTISEMENT"
        )
        req = urllib.request.Request(url, headers={
            'accept': '*/*',
            'origin': 'https://fem.encar.com',
            'referer': 'https://fem.encar.com/',
            'user-agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
        })
        payload = None
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                available = resp.status == 200
                if available:
                    payload = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as http_err:
            available = False if http_err.code == 404 else None

        new_price = None
        old_price = None
        price_changed = False
        if available and isinstance(payload, dict):
            adv = payload.get('advertisement') or {}
            raw_price = adv.get('price')
            if isinstance(raw_price, (int, float)) and raw_price > 0:
                new_price = int(raw_price) * 10000
                from django_tenants.utils import schema_context, get_public_schema_name
                with schema_context(get_public_schema_name()):
                    try:
                        car = ApiCar.objects.only('id', 'price').get(lot_number=lot_number)
                        if car.price != new_price:
                            old_price = car.price
                            ApiCar.objects.filter(pk=car.pk).update(price=new_price)
                            price_changed = True
                    except ApiCar.DoesNotExist:
                        pass

        return JsonResponse({
            'available': available,
            'price': new_price,
            'old_price': old_price,
            'price_changed': price_changed,
        })
    except Exception:
        return JsonResponse({
            'available': None,
            'price': None,
            'old_price': None,
            'price_changed': False,
        })


