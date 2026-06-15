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


# Some image CDNs (e.g. Autowini's imagebox) sit behind a WAF that 403s plain
# requests — a full browser header set gets through.
_BROWSER_IMG_HEADERS = {
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "cross-site",
}
_AUTOWINI_IMG_HEADERS = {**_BROWSER_IMG_HEADERS, "Referer": "https://www.autowini.com/", "Sec-Fetch-Site": "same-site"}


def _download_image(item, url, name_hint, headers=None):
    try:
        r = requests.get(url, timeout=25, headers=headers or _BROWSER_IMG_HEADERS)
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
                download_images=True, limit=2000, image_headers=None):
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
                if _download_image(obj, img_url, f"{row_kind}_{obj.pk}", headers=image_headers):
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


# ──────────────────── Autowini parts API (Korean wholesaler) ────────────────────
# Public JSON feed: 400k+ Korean OEM/used/rebuilt parts. No auth needed.
AUTOWINI_API = "https://v2api.autowini.com/items/parts"
_AW_MAKES = ["Hyundai", "Kia", "Genesis", "SsangYong", "Ssang Yong", "Chevrolet", "Daewoo",
             "Renault", "Samsung", "GM", "Toyota", "Nissan", "Honda", "BMW", "Mercedes", "Audi"]


def _autowini_headers():
    return {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.autowini.com",
        "Referer": "https://www.autowini.com/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "wini-code-select-country": "C1450",
    }


def _autowini_map(it):
    cond = (it.get("condition") or "").strip().lower()
    if cond in ("genuine", "oem", "original"):
        origin, condition = "genuine", "new"
    elif cond == "aftermarket":
        origin, condition = "aftermarket", "new"
    elif cond == "rebuilt":
        origin, condition = "aftermarket", "used"
    elif cond == "used":
        origin, condition = "", "used"
    else:
        origin, condition = "", "new"

    cat1 = (it.get("category1") or "")
    kind = "accessory" if "accessor" in cat1.lower() else "part"
    name = re.sub(r"\s+", " ", (it.get("itemName") or "")).strip()
    fits_make = next((m for m in _AW_MAKES if m.lower() in name.lower()), "")
    thumbs = it.get("thumbnails") or []
    price = it.get("discountPrice") or it.get("price") or None

    pn = (it.get("partNumber") or "").strip()
    if pn.upper() in ("PARTNUMBER", "N/A", "NA", "-", "NONE"):
        pn = ""  # feed placeholder = no real number

    return {
        "kind": kind, "name": name,
        "part_number": pn,
        "category": (it.get("category2") or it.get("category1") or "").strip(),
        "brand": fits_make, "fits_make": fits_make,
        "origin": origin, "condition": condition, "price": price,
        "in_stock": "1" if it.get("status") == "FOR_SALE" else "0",
        "image": thumbs[0] if thumbs else "",
        "external_id": (it.get("listingId") or it.get("code") or "").strip(),
    }


def fetch_autowini_rows(pages=3, page_size=32, fitting="CAR", sorting="recentDate", start_page=1):
    rows = []
    for p in range(start_page, start_page + pages):
        r = requests.get(AUTOWINI_API, params={
            "fittingCategory": fitting, "sorting": sorting,
            "pageOffset": p, "pageSize": min(page_size, 32),
        }, headers=_autowini_headers(), timeout=30)
        r.raise_for_status()
        items = ((r.json() or {}).get("data") or {}).get("items") or []
        if not items:
            break
        rows.extend(_autowini_map(it) for it in items)
    return rows


def import_autowini(pages=3, fitting="CAR", currency="USD", source="autowini",
                    download_images=True, limit=2000, start_page=1, dry_run=False):
    rows = fetch_autowini_rows(pages=pages, fitting=fitting, start_page=start_page)
    if dry_run:
        return {"fetched": len(rows), "sample": rows[:8], "dry_run": True}
    return import_rows(rows, kind="part", source=source, default_currency=currency,
                       download_images=download_images, limit=limit,
                       image_headers=_AUTOWINI_IMG_HEADERS)
