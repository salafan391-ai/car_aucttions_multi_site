# Dashboard guide: Customer orders (section key: `orders`)

Needs the `orders` section. That one section grants both viewing **and** changing
status — there is no view-only level.

A customer browsing a car submits an offer from the car's page. It arrives here as
a طلب with status **قيد المراجعة**.

## The orders page

Path: `/staff/orders/` — tile **إدارة الطلبات** on the dashboard.

A table of: **#**, **العميل**, **السيارة**, **السعر**, **التاريخ**, **الحالة**,
**إجراء**. Newest first, 25 per page (**السابق** / **التالي**).

Filter by **الحالة** (or **الكل**), and search with **بحث**, then **تصفية**.

**The search box does not search car names.** Despite the السيارة column being
right there, بحث only looks at the customer's username, email, ملاحظات العميل, and
ملاحظات الإدارة — the placeholder says so: «اسم المستخدم، البريد، الملاحظات…».
Searching for a car model returns nothing. If an admin says search is "broken",
this is why: tell them to filter by الحالة or search the customer instead.

## Changing an order's status

Pick a status in the row and press **حفظ**. The four statuses are:

- **قيد المراجعة** — the default when the order arrives.
- **مقبول**
- **مرفوض**
- **مكتمل** — see the warning below. This one is not just a label.

### ⚠️ Setting مكتمل sells the car — silently and permanently

The moment an order's status becomes **مكتمل**, three things happen automatically,
with no confirmation prompt and nothing on screen saying so:

1. The car's status flips to **تم البيع**, so it disappears from the available
   listings on the public site.
2. A **سيارة مباعة** record is created (buyer = the customer, sale price = their
   offer price).
3. The completion time is stamped on the order.

**Changing the status back does not undo any of it.** Setting the order back to
مرفوض or قيد المراجعة leaves the car sold, leaves the سيارة مباعة record in place,
and leaves the completion time stamped. Only the move *into* مكتمل is automatic;
there is no automatic reversal.

So: مكتمل means "this sale is done", not "I'm tidying up the list". If an admin
asks how to undo a مكتمل they set by mistake, do not pretend the dashboard can do
it — tell them the car stays marked تم البيع and they should contact support to
correct it.

If two different customers order the same car and both orders are set مكتمل, only
the first creates the sold record. The second changes nothing, and the sold record
keeps the first buyer's name and price.

### ⚠️ The customer is NOT emailed when you change the status

Accepting, rejecting, or completing an order from this page sends the customer
**no notification at all**. The customer only finds out by visiting **طلباتي** on
the site themselves.

This surprises admins constantly. If someone asks "does the customer know I
accepted?" the honest answer is no — if they want the customer informed, they must
contact them directly (phone/WhatsApp). The customer *is* emailed once, when they
first place the order — not on any later change.

## رد الإدارة — cannot be written from the dashboard

The customer's own order page shows a **رد الإدارة** panel, and orders have a
**ملاحظات الإدارة** field. But there is no input for it anywhere on the orders
page, and tenant sites cannot reach the Django admin where it would be editable.

So this field cannot be filled in from your dashboard at all. If an admin asks how
to reply to a customer on the order, tell them that panel can't be filled from the
dashboard and they should contact the customer directly. Do not invent a page for
it, and do not send them to `/admin/` — that returns "not found" on every tenant
site.

## What staff cannot open

The order **detail** page belongs to the customer who placed the order. A staff
member who opens that link gets a "not found" page — the row in the orders table
is everything staff can see. That's expected, not a bug.

## What the customer sees

- They place an offer from a car's page, entering **السعر المعروض** and optional
  **ملاحظات**, then **تأكيد الطلب**. They see «تم إرسال طلبك بنجاح! سنتواصل معك
  قريباً.»
- They track their own orders at **طلباتي**, where each shows the status badge
  (قيد المراجعة / مقبول / مرفوض / مكتمل), their offer, and the date.

Note the customer's confirmation message promises someone will contact them — and
nothing does that automatically. Following up is a manual job.

## Related

Orders and invoices are separate. An order becoming مكتمل marks the car sold and
creates a sold record, but it does **not** create a فاتورة. Invoicing is its own
flow in the `sales` section.
