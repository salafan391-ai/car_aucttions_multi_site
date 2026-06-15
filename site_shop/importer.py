"""Generic catalogue feed importer for ShopItem.

Maps flexible CSV/dict rows (Korean wholesaler exports, distributor feeds, etc.)
onto ShopItem, upserting so re-imports update instead of duplicating. Shared by
the `import_shop_csv` management command and the staff upload page.
"""
import csv
import io
import os
import re

import requests
from django.core.files.base import ContentFile


def _key(s):
    """Normalize a header/alias: lower, trim, collapse spaces & hyphens to '_'."""
    return re.sub(r"[\s\-]+", "_", (s or "").strip().lower())


# Header aliases (lower-cased, stripped). First non-empty wins.
ALIASES = {
    "name":        ["name", "title", "product", "product_name", "الاسم", "اسم", "اسم المنتج"],
    "kind":        ["kind", "type", "النوع"],
    "category":    ["category", "cat", "الفئة", "القسم"],
    "brand":       ["brand", "make", "manufacturer", "الماركة", "الشركة"],
    "part_number": ["part_number", "partnumber", "part_no", "partno", "oem", "oem_no", "oem_number", "mpn", "sku", "رقم القطعة", "رقم"],
    "origin":      ["origin", "source_type", "genuine", "المصدر", "النوعية"],
    "price":       ["price", "cost", "amount", "السعر", "السعر بالريال"],
    "currency":    ["currency", "cur", "العملة"],
    "condition":   ["condition", "state", "الحالة"],
    "in_stock":    ["in_stock", "stock", "available", "availability", "qty", "quantity", "متوفر", "الكمية"],
    "fits_make":   ["fits_make", "fitment_make", "compatible_make", "vehicle_make", "يناسب الماركة"],
    "fits_model":  ["fits_model", "fitment_model", "compatible_model", "vehicle_model", "model", "يناسب الموديل"],
    "description": ["description", "desc", "details", "الوصف", "التفاصيل"],
    "image":       ["image", "image_url", "imageurl", "img", "photo", "image_link", "picture", "الصورة", "رابط الصورة"],
    "external_id": ["external_id", "id", "item_id", "product_id", "sku_id", "code", "المعرف", "الكود"],
}


def _norm_headers(row):
    return {_key(k): (v if v is not None else "") for k, v in row.items()}


def _pick(row, field):
    for a in ALIASES[field]:
        v = row.get(_key(a))
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return ""


def _norm_origin(v):
    v = (v or "").strip().lower()
    if v in ("genuine", "oem", "original", "أصلي", "اصلي", "وكالة"):
        return "genuine"
    if v in ("aftermarket", "after market", "بديل", "تجاري", "commercial"):
        return "aftermarket"
    return ""


def _norm_condition(v):
    v = (v or "").strip().lower()
    if v in ("used", "second hand", "secondhand", "مستعمل"):
        return "used"
    return "new"


def _truthy_stock(v):
    v = (v or "").strip().lower()
    if v in ("0", "false", "no", "out", "out of stock", "نفد", "غير متوفر", "لا"):
        return False
    return True


def _download_image(item, url, name_hint):
    try:
        r = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
        if not r.ok or not r.content:
            return False
        ext = os.path.splitext(url.split("?")[0])[1].lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        item.image.save(f"{name_hint}{ext}", ContentFile(r.content), save=True)
        return True
    except Exception:
        return False


def import_rows(rows, *, kind="part", source="csv", default_currency="SAR",
                download_images=True, limit=2000):
    """Upsert an iterable of dict rows. Returns a result summary dict."""
    from .models import ShopItem

    created = updated = skipped = images = 0
    errors = []

    for i, raw in enumerate(rows):
        if i >= limit:
            errors.append(f"تم تجاوز الحد ({limit} صف) — تم تجاهل الباقي.")
            break
        row = _norm_headers(raw)
        name = _pick(row, "name")
        if not name:
            skipped += 1
            continue

        row_kind = (_pick(row, "kind") or "").lower()
        if row_kind in ("accessory", "accessories", "اكسسوار", "إكسسوارات", "اكسسوارات"):
            row_kind = "accessory"
        elif row_kind in ("part", "parts", "قطعة", "قطع", "قطع غيار"):
            row_kind = "part"
        else:
            row_kind = kind

        ext_id = _pick(row, "external_id")
        part_number = _pick(row, "part_number")

        price_raw = _pick(row, "price").replace(",", "")
        try:
            price = int(float(price_raw)) if price_raw else None
        except ValueError:
            price = None

        fields = dict(
            kind=row_kind, name=name,
            category=_pick(row, "category"), brand=_pick(row, "brand"),
            part_number=part_number, origin=_norm_origin(_pick(row, "origin")),
            price=price, currency=(_pick(row, "currency") or default_currency).upper()[:3] or default_currency,
            condition=_norm_condition(_pick(row, "condition")),
            in_stock=_truthy_stock(_pick(row, "in_stock")),
            fits_make=_pick(row, "fits_make"), fits_model=_pick(row, "fits_model"),
            description=_pick(row, "description"),
            source=source, external_id=ext_id,
        )

        # Upsert key: external_id > part_number > name (scoped to this source/kind).
        if ext_id:
            obj = ShopItem.objects.filter(source=source, external_id=ext_id).first()
        elif part_number:
            obj = ShopItem.objects.filter(kind=row_kind, part_number__iexact=part_number).first()
        else:
            obj = ShopItem.objects.filter(kind=row_kind, name=name).first()

        is_new = obj is None
        if is_new:
            obj = ShopItem(**fields)
        else:
            for k, v in fields.items():
                setattr(obj, k, v)
        obj.save()
        created += 1 if is_new else 0
        updated += 0 if is_new else 1

        if download_images and not obj.image:
            img_url = _pick(row, "image")
            if img_url and img_url.startswith(("http://", "https://")):
                if _download_image(obj, img_url, f"{row_kind}_{obj.pk}"):
                    images += 1

    return {"created": created, "updated": updated, "skipped": skipped,
            "images": images, "errors": errors, "total": created + updated}


def import_csv_text(text, **kwargs):
    """Parse CSV text (handles UTF-8 / BOM) and import its rows."""
    reader = csv.DictReader(io.StringIO(text))
    return import_rows(reader, **kwargs)


def import_csv_url(url, **kwargs):
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return import_csv_text(r.content.decode("utf-8-sig", errors="replace"), **kwargs)
