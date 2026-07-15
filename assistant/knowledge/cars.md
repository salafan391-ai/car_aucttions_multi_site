# Dashboard guide: Cars & inventory (section key: `cars`)

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

All of these need the `cars` section — they are **not** site-admin-only.

**Save a car from the auction listings** — browse at `/auctions/browse/` (read-only,
filter by auction date, auction name, entry number, or free text) and save any car
into your own inventory instead of re-typing it. Saving twice is safe: you get
«هذه السيارة محفوظة لديك بالفعل» rather than a duplicate. Suggest this whenever
someone asks about adding a car that already exists in the auction feed.

**HappyCar import** — `/dashboard/import-happycar/`. Runs in the background; you'll
see «بدأ الاستيراد في الخلفية». Only one import per site at a time — a second
attempt says «استيراد جارٍ بالفعل، الرجاء الانتظار حتى ينتهي». Options include how
many pages, whether to fetch the gallery, and whether to download images.

> ⚠️ **حذف السيارات المستوردة سابقاً وغير الموجودة في هذا الاستيراد** is a
> destructive checkbox sitting in an ordinary-looking import form, and it does
> **not** ask for confirmation. Ticking it deletes previously-imported cars that
> aren't in this run. If someone is unsure, tell them to leave it unticked — an
> import without it only adds and updates.

There is also a reset button for when an import appears stuck. It only clears the
"import is running" flag; it does not undo anything.

## Deleting damaged cars in bulk

`/dashboard/damaged-cars/delete-unsold/` deletes **every imported damaged car that
isn't marked تم البيع**, along with their photos.

This is irreversible. It does ask for confirmation first («لا يمكن التراجع») and it
only ever touches this site's own cars. Note it needs only the `cars` section — a
limited staff member can do it, not just the site admin.

## Shareable car collections (`cars` section)

`/dashboard/share/` — pick any number of cars, from both the shared catalogue and
your own inventory, and get **one link to send a customer**: «إنشاء رابط المشاركة»,
then **نسخ**. Up to 60 cars per link; the page lists your most recent 50 links.

The link looks like `/c/<code>/` and is **public — anyone holding it can open it,
with no login**. The code is unguessable, but the link **never expires**. There is
no way to disable a link other than deleting the collection («تم حذف المجموعة»),
which is the honest answer if an admin asks how to revoke one they sent by mistake.

A related page, `/share-cart/`, can push the cart to the dealership's Telegram —
but the Telegram buttons only work for the site admin. A limited staff member with
`cars` can open the cart and see the button, and clicking it fails. That's a known
rough edge, not something they're doing wrong.

## Billing a car

From a car, an invoice can be created at `/our-cars/<id>/invoice/new/`, which then
leads to receipts, contract, and shipment. That flow belongs to the `sales`
section — an admin without `sales` cannot reach it. See the invoices guide.

Note this affects inventory: **creating an invoice marks the car تم البيع
automatically**, so a car can leave the available listings via the sales flow
without anyone touching its status field.

## Permissions in this section

Adding and editing cars require the `cars` section. The public car list
(`/our-cars/`) is visible to everyone. Managing staff accounts is site-admin only
and is not part of the `cars` section.
