from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Q
from django.urls import reverse
from django.views.decorators.http import require_POST

import re

from site_cars.image_utils import optimize_image
from .models import ShopItem, ShopItemImage, categories_for


KIND_LABELS = {
    "part": {"ar": "قطع غيار", "en": "Car Parts", "es": "Repuestos", "ru": "Запчасти"},
    "accessory": {"ar": "إكسسوارات", "en": "Accessories", "es": "Accesorios", "ru": "Аксессуары"},
}


def _is_public_schema():
    return getattr(connection, "schema_name", "public") == "public"


# ──────────────────────────── Public ────────────────────────────

def _shop_list(request, kind):
    """Public catalogue for one kind (part / accessory)."""
    labels = KIND_LABELS[kind]
    if _is_public_schema():
        items = ShopItem.objects.none()
        categories, brands = [], []
    else:
        qs = ShopItem.objects.filter(kind=kind)

        q = (request.GET.get("q") or "").strip()
        category = (request.GET.get("category") or "").strip()
        brand = (request.GET.get("brand") or "").strip()
        condition = (request.GET.get("condition") or "").strip()
        origin = (request.GET.get("origin") or "").strip()
        in_stock = request.GET.get("in_stock")

        if q:
            cond = Q(name__icontains=q) | Q(description__icontains=q) | Q(brand__icontains=q) | Q(fits_make__icontains=q) | Q(fits_model__icontains=q) | Q(part_number__icontains=q)
            qnorm = re.sub(r"[^A-Za-z0-9]", "", q).upper()
            if qnorm:
                cond |= Q(part_number_norm__icontains=qnorm)
            qs = qs.filter(cond)
        if category:
            qs = qs.filter(category__iexact=category)
        if brand:
            qs = qs.filter(brand__iexact=brand)
        if condition in ("new", "used"):
            qs = qs.filter(condition=condition)
        if origin in ("genuine", "aftermarket"):
            qs = qs.filter(origin=origin)
        if in_stock == "1":
            qs = qs.filter(in_stock=True)

        # Categories + brands are dynamic — taken from the items actually present.
        categories = categories_for(kind)
        brands = sorted({b for b in ShopItem.objects.filter(kind=kind).exclude(brand="").values_list("brand", flat=True)})

        paginator = Paginator(qs, 24)
        items = paginator.get_page(request.GET.get("page"))

    tenant = getattr(connection, "tenant", None)
    feature_active = bool(getattr(
        tenant, "show_parts" if kind == "part" else "show_accessories", True))
    # True only when the catalogue has NO items of this kind at all (ignoring
    # filters) — that's when we offer the "request it" form instead.
    catalogue_empty = (not _is_public_schema()
                       and not ShopItem.objects.filter(kind=kind).exists())

    context = {
        "items": items,
        "kind": kind,
        "is_part": kind == "part",
        "feature_active": feature_active,
        "catalogue_empty": catalogue_empty,
        "kind_label_ar": labels["ar"],
        "kind_labels": labels,
        "categories": categories,
        "brands": brands,
        "active_filters": {
            "q": request.GET.get("q", ""),
            "category": request.GET.get("category", ""),
            "brand": request.GET.get("brand", ""),
            "condition": request.GET.get("condition", ""),
            "origin": request.GET.get("origin", ""),
            "in_stock": request.GET.get("in_stock", ""),
        },
    }
    return render(request, "site_shop/shop_list.html", context)


def parts_list(request):
    return _shop_list(request, "part")


def accessories_list(request):
    return _shop_list(request, "accessory")


@require_POST
def shop_request(request):
    """Handle the 'request a part/accessory' form shown when the catalogue is
    empty. Saves the request and notifies the tenant by email (best effort)."""
    if _is_public_schema():
        return redirect("home")

    kind = request.POST.get("kind")
    if kind not in ("part", "accessory"):
        kind = "part"

    phone = (request.POST.get("phone") or "").strip()
    item_description = (request.POST.get("item_description") or "").strip()
    car_vin = (request.POST.get("car_vin") or "").strip()
    redirect_name = "parts_list" if kind == "part" else "accessories_list"

    if not car_vin or not phone or not item_description:
        messages.error(request, "الرجاء إدخال رقم الهيكل (VIN) ورقم الهاتف ووصف الطلب.")
        return redirect(redirect_name)

    from .models import ShopRequest
    photo = request.FILES.get("photo")
    if photo and not (photo.content_type or "").startswith("image/"):
        photo = None
    req = ShopRequest.objects.create(
        kind=kind,
        car_vin=car_vin,
        car_description=(request.POST.get("car_description") or "").strip(),
        phone=phone,
        email=(request.POST.get("email") or "").strip(),
        item_description=item_description,
        image=photo,
    )

    # Notify the tenant by email (best effort — never blocks the response).
    try:
        from site_cars.email_utils import send_tenant_email, get_tenant_email_config
        cfg = get_tenant_email_config() or {}
        to_addr = (cfg.get("email") if isinstance(cfg, dict) else None) \
            or getattr(getattr(connection, "tenant", None), "email", None)
        if to_addr:
            label = KIND_LABELS[kind]["ar"]
            photo_html = ""
            if req.image:
                img_url = request.build_absolute_uri(req.image.url)
                photo_html = (
                    f'<p><b>الصورة:</b> <a href="{img_url}">عرض الصورة</a></p>'
                    f'<p><img src="{img_url}" style="max-width:360px;border-radius:8px"></p>'
                )
            body = (
                f"<h3>طلب {label} جديد</h3>"
                f"<p><b>رقم الهاتف:</b> {req.phone}</p>"
                f"<p><b>البريد:</b> {req.email or '—'}</p>"
                f"<p><b>رقم الهيكل (VIN):</b> {req.car_vin or '—'}</p>"
                f"<p><b>وصف السيارة:</b> {req.car_description or '—'}</p>"
                f"<p><b>المطلوب:</b> {req.item_description}</p>"
                f"{photo_html}"
            )
            send_tenant_email(to_addr, f"طلب {label} جديد", body, email_type="shop_request")
    except Exception:
        pass

    messages.success(request, "تم إرسال طلبك بنجاح، سنتواصل معك قريباً.")
    return redirect(redirect_name)


@staff_member_required
def shop_requests(request):
    """Dashboard list of customer part/accessory requests (from the empty-catalogue form)."""
    if _is_public_schema():
        messages.error(request, "غير متاح من النطاق العام")
        return redirect("home")
    from .models import ShopRequest
    flt = request.GET.get("filter") or "unhandled"
    qs = ShopRequest.objects.all()
    if flt != "all":
        qs = qs.filter(is_handled=False)
    paginator = Paginator(qs, 30)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "site_shop/shop_requests.html", {
        "requests": page,
        "filter": flt,
        "unhandled_count": ShopRequest.objects.filter(is_handled=False).count(),
    })


@staff_member_required
@require_POST
def shop_request_toggle(request, pk):
    """Toggle a request's handled flag."""
    if _is_public_schema():
        return redirect("home")
    from .models import ShopRequest
    req = get_object_or_404(ShopRequest, pk=pk)
    req.is_handled = not req.is_handled
    req.save(update_fields=["is_handled"])
    return redirect(request.POST.get("next") or "shop_requests")


def _shop_detail(request, pk, kind):
    item = get_object_or_404(ShopItem, pk=pk, kind=kind)
    related = ShopItem.objects.filter(kind=kind).exclude(pk=item.pk)
    if item.category:
        related = related.filter(category__iexact=item.category)
    related = related[:8]
    context = {
        "item": item,
        "kind": kind,
        "is_part": kind == "part",
        "kind_label_ar": KIND_LABELS[kind]["ar"],
        "kind_labels": KIND_LABELS[kind],
        "related": related,
    }
    return render(request, "site_shop/shop_detail.html", context)


def parts_detail(request, pk):
    return _shop_detail(request, pk, "part")


def accessories_detail(request, pk):
    return _shop_detail(request, pk, "accessory")


# ──────────────────────────── Staff CRUD ────────────────────────────

def _kind_param(request, default="part"):
    k = (request.GET.get("kind") or request.POST.get("kind") or default).strip()
    return k if k in ("part", "accessory") else default


def _apply_fields(item, request):
    """Populate a ShopItem from request.POST (shared by add + edit)."""
    item.kind = _kind_param(request, item.kind or "part")
    item.name = (request.POST.get("name") or "").strip()
    item.category = (request.POST.get("category") or "").strip()
    item.brand = (request.POST.get("brand") or "").strip()
    item.currency = (request.POST.get("currency") or "SAR").strip() or "SAR"
    item.condition = (request.POST.get("condition") or "new").strip()
    item.origin = (request.POST.get("origin") or "").strip()
    item.part_number = (request.POST.get("part_number") or "").strip()
    item.fits_make = (request.POST.get("fits_make") or "").strip()
    item.fits_model = (request.POST.get("fits_model") or "").strip()
    item.description = (request.POST.get("description") or "").strip()
    item.in_stock = "in_stock" in request.POST
    item.is_featured = "is_featured" in request.POST

    raw_price = (request.POST.get("price") or "").strip().replace(",", "")
    item.price = int(float(raw_price)) if raw_price else None


def _save_images(item, request):
    if "image" in request.FILES:
        item.image = request.FILES["image"]
        item.save()
    gallery = request.FILES.getlist("gallery")
    start = item.images.count()
    for i, f in enumerate(gallery):
        ShopItemImage.objects.create(item=item, image=f, order=start + i)


@staff_member_required
def shop_manage(request):
    """Staff inventory list for parts OR accessories (kind filter)."""
    if _is_public_schema():
        messages.error(request, "غير متاح من النطاق العام")
        return redirect("home")
    kind = _kind_param(request)
    qs = ShopItem.objects.filter(kind=kind)
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(brand__icontains=q) | Q(category__icontains=q))
    paginator = Paginator(qs, 30)
    items = paginator.get_page(request.GET.get("page"))
    return render(request, "site_shop/shop_manage.html", {
        "items": items, "kind": kind, "is_part": kind == "part",
        "kind_label_ar": KIND_LABELS[kind]["ar"], "q": q,
    })


@staff_member_required
def shop_add(request):
    if _is_public_schema():
        messages.error(request, "غير متاح من النطاق العام")
        return redirect("home")
    kind = _kind_param(request)
    if request.method == "POST":
        item = ShopItem()
        _apply_fields(item, request)
        if not item.name:
            messages.error(request, "الاسم مطلوب")
        else:
            item.save()
            _save_images(item, request)
            messages.success(request, "تمت الإضافة بنجاح")
            return redirect(f"{reverse('shop_manage')}?kind={item.kind}")
    return render(request, "site_shop/shop_form.html", {
        "kind": kind, "is_part": kind == "part",
        "kind_label_ar": KIND_LABELS[kind]["ar"], "item": None,
        "category_options": categories_for(kind),
    })


@staff_member_required
def shop_edit(request, pk):
    if _is_public_schema():
        messages.error(request, "غير متاح من النطاق العام")
        return redirect("home")
    item = get_object_or_404(ShopItem, pk=pk)
    if request.method == "POST":
        _apply_fields(item, request)
        if not item.name:
            messages.error(request, "الاسم مطلوب")
        else:
            item.save()
            _save_images(item, request)
            messages.success(request, "تم الحفظ")
            return redirect("shop_edit", pk=item.pk)
    return render(request, "site_shop/shop_form.html", {
        "kind": item.kind, "is_part": item.kind == "part",
        "kind_label_ar": KIND_LABELS[item.kind]["ar"], "item": item,
        "category_options": categories_for(item.kind),
    })


@staff_member_required
def shop_delete(request, pk):
    if _is_public_schema():
        return redirect("home")
    item = get_object_or_404(ShopItem, pk=pk)
    kind = item.kind
    if request.method == "POST":
        if item.image:
            item.image.delete(save=False)
        item.delete()
        messages.success(request, "تم الحذف")
        return redirect(f"{reverse('shop_manage')}?kind={kind}")
    return render(request, "site_shop/shop_delete.html", {"item": item, "kind": kind})


@staff_member_required
@require_POST
def shop_delete_image(request, pk, image_id):
    if _is_public_schema():
        return redirect("home")
    item = get_object_or_404(ShopItem, pk=pk)
    img = get_object_or_404(ShopItemImage, pk=image_id, item=item)
    img.image.delete(save=False)
    img.delete()
    return redirect("shop_edit", pk=item.pk)


@staff_member_required
@require_POST
def shop_toggle_stock(request, pk):
    if _is_public_schema():
        return redirect("home")
    item = get_object_or_404(ShopItem, pk=pk)
    item.in_stock = not item.in_stock
    item.save(update_fields=["in_stock", "updated_at"])
    return redirect(request.META.get("HTTP_REFERER") or "shop_manage")


@staff_member_required
def shop_import(request):
    """Upload a CSV catalogue feed (e.g. a Korean wholesaler export) and upsert
    it into the parts/accessories inventory."""
    if _is_public_schema():
        messages.error(request, "غير متاح من النطاق العام")
        return redirect("home")
    kind = _kind_param(request)
    if request.method == "POST" and request.POST.get("action") == "autowini":
        from .importer import import_autowini
        try:
            pages = max(1, min(int(request.POST.get("pages") or 2), 5))
        except ValueError:
            pages = 2
        try:
            res = import_autowini(
                pages=pages, fitting=(request.POST.get("fitting") or "CAR"),
                currency=(request.POST.get("currency") or "USD"), source="autowini",
                download_images="no_images" not in request.POST, limit=400)
        except Exception as e:
            messages.error(request, f"تعذّر الجلب من Autowini: {e}")
            return redirect(f"{reverse('shop_import')}?kind={kind}")
        messages.success(request, f"Autowini — أُضيف {res['created']}، حُدّث {res['updated']}، صور {res['images']}")
        return redirect(f"{reverse('shop_manage')}?kind={kind}")

    if request.method == "POST":
        from .importer import import_csv_text, import_csv_url
        source = (request.POST.get("source") or "csv").strip()[:40] or "csv"
        currency = (request.POST.get("currency") or "SAR").strip() or "SAR"
        download_images = "no_images" not in request.POST
        common = dict(kind=kind, source=source, default_currency=currency,
                      download_images=download_images, limit=1000)
        try:
            url = (request.POST.get("url") or "").strip()
            if request.FILES.get("file"):
                text = request.FILES["file"].read().decode("utf-8-sig", errors="replace")
                res = import_csv_text(text, **common)
            elif url:
                res = import_csv_url(url, **common)
            else:
                messages.error(request, "أرفق ملف CSV أو ضع رابطاً")
                return redirect(f"{reverse('shop_import')}?kind={kind}")
        except Exception as e:
            messages.error(request, f"تعذّر الاستيراد: {e}")
            return redirect(f"{reverse('shop_import')}?kind={kind}")
        messages.success(request, f"تم الاستيراد — أُضيف {res['created']}، حُدّث {res['updated']}، صور {res['images']}، تم تخطّي {res['skipped']}")
        for e in res["errors"][:5]:
            messages.warning(request, e)
        return redirect(f"{reverse('shop_manage')}?kind={kind}")
    return render(request, "site_shop/shop_import.html", {
        "kind": kind, "is_part": kind == "part", "kind_label_ar": KIND_LABELS[kind]["ar"],
    })
