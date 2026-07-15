# Dashboard guide: Cars & inventory (section key: `cars`)

Scope note: this file covers the cars/inventory section only. If a question is
about invoices, orders, ratings, staff accounts, the page builder, or billing,
say those parts of the guide aren't written yet and point the admin at support.

## Adding a car

Path: `/our-cars/add/` — button "إضافة سيارة" on the dashboard, or "إدارة السيارات"
→ "إضافة سيارة جديدة". Requires the `cars` section.

The form is grouped into five blocks, in this order on screen:

**المعلومات الأساسية** — العنوان*, الشركة المصنعة*, الموديل*, سنة الصنع*, اللون,
رقم الشاسيه (VIN), رقم اللوحة. Starred fields are required; saving without them fails.

**المواصفات** — المسافة المقطوعة (كم), ناقل الحركة (أوتوماتيك / مانيوال),
الوقود (بنزين / ديزل / هايبرد / كهربائي), نوع الهيكل (سيدان / هاتشباك / كوبيه /
فان / بيك أب), المحرك, نظام الدفع (دفع أمامي / دفع خلفي / دفع رباعي). All optional.

**السعر والحالة** — السعر*, العملة (KRW ₩ default, SAR ﷼, USD $, AED د.إ, EUR €),
الحالة (متاح / قيد الانتظار / تم البيع — defaults to متاح), سيارة مميزة checkbox
(featured cars get surfaced on the site's front page).

**الوصف** — free text, optional.

**الصور** — see the images section below.

## Images and video

- **الصورة الرئيسية** (`image`) — one main photo. This is the thumbnail buyers see
  in listings. A car with no main image looks broken in the list; always set one.
- **صور إضافية (معرض الصور)** (`gallery`) — multiple files at once, **maximum 20**.
  Uploading more than 20 will not all be kept.
- **صورة تقرير الفحص الفني** (`inspection_image`) — optional JPG/PNG of the
  inspection report.
- **فيديو الفحص** — two mutually useful options: upload a file (`inspection_video`,
  stored on cloud storage, not the web server), **or** paste a link
  (`inspection_video_url`, YouTube or direct). For large files the **link is
  better** — the form itself says so. If an admin complains a video upload is slow
  or times out, tell them to use the link field instead.

All uploaded images are automatically compressed and resized on save (max
1200×900, quality 85). Admins do not need to resize before uploading.

To remove one gallery image later, open the car's edit page and delete that image
there (`/our-cars/<id>/delete-image/<image_id>/`) — it does not delete the car.

## Editing, status, deleting

- Edit: `/our-cars/<id>/edit/` — same form as adding.
- Change status only: `/our-cars/<id>/status/` — a quicker path than a full edit
  when a car sells. Statuses: متاح, قيد الانتظار, تم البيع.
- Sold cars are listed at `/sold-cars/`.
- Delete: `/our-cars/<id>/delete/`. Deleting is permanent — if the admin only wants
  to hide a sold car, changing الحالة to تم البيع is the right move, not deleting.

## Text normalization — explains a common confusion

On save, the site automatically lowercases and normalizes الشركة المصنعة, الموديل,
الوقود, ناقل الحركة, نوع الهيكل, and اللون. So typing "BMW" stores `bmw`, and the
site displays it back as "BMW" through its display filters.

If an admin asks why their capitalization "changed" or looks wrong in the database:
this is intentional and display is handled automatically. They should not try to
work around it by re-typing. If a name displays wrongly on the public site, that's
a translation-dictionary gap, not something the admin can fix from the form —
route it to support.

## Importing cars instead of typing them

- **HappyCar import**: `/dashboard/import-happycar/` — bulk-imports listings.
- **Save a car from the public/auction listings**: browsing at `/auctions/browse/`,
  an admin can save a listing into their own inventory
  (`/our-cars/save/<car_id>/`) instead of re-entering it by hand. Worth suggesting
  whenever someone asks about adding a car that already exists in the auction feed.
- **Auction JSON upload**: `/upload-auction/`.

## Billing a car

From a car, an invoice can be created at `/our-cars/<id>/invoice/new/`, which then
leads to receipts, contract, and shipment. That flow belongs to the `sales`
section — an admin without `sales` cannot reach it. Details aren't in this guide yet.

## Permissions in this section

Adding and editing cars require the `cars` section. The public car list
(`/our-cars/`) is visible to everyone. Managing staff accounts is site-admin only
and is not part of the `cars` section.
