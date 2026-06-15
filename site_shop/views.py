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

        # Curated categories first, plus any custom ones already in use.
        existing = {c for c in ShopItem.objects.filter(kind=kind).exclude(category="").values_list("category", flat=True)}
        curated = categories_for(kind)
        categories = curated + sorted(existing - set(curated))
        brands = sorted({b for b in ShopItem.objects.filter(kind=kind).exclude(brand="").values_list("brand", flat=True)})

        paginator = Paginator(qs, 24)
        items = paginator.get_page(request.GET.get("page"))

    context = {
        "items": items,
        "kind": kind,
        "is_part": kind == "part",
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
