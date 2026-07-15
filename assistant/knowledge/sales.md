# Dashboard guide: Invoices, receipts & shipping (section key: `sales`)

Everything here needs the `sales` section. The one exception is the public
tracking page, which needs no login at all (see the end of this file).

The flow is: a car → **فاتورة** (invoice) → one or more **سند قبض** (payment
receipts) → optionally a **عقد** (contract) and a **شحنة** (shipment).

## Creating an invoice

Path: `/our-cars/<id>/invoice/new/` — reached from the car itself.

Only **اسم المشتري** is required. السعر defaults to the car's own price if left
blank, and التاريخ defaults to today. You can also fill رقم الهوية, جوال المشتري,
عنوان المشتري, and الوصف.

Two things happen automatically that admins should know about:

1. **The car is marked تم البيع.** Creating an invoice flips the car's status to
   sold. The admin does not need to change it separately — and if they created an
   invoice by mistake, the car is now hidden from the available listings.
2. **رقم الفاتورة is generated**, in the form `INV-YYYYMMDD-00001`. It cannot be
   typed or changed — it stays locked afterwards for auditability.

**One invoice per car, from this button.** If the car already has an invoice, the
"invoice" button does not make a second one — it shows «توجد فاتورة سابقة لهذه
السيارة» and opens the existing invoice instead. To bill several cars together,
don't look for a second invoice; add the other cars as **بنود** to the existing
one (below).

## Several cars on one invoice

Open `/our-cars/<id>/invoice/<invoice_id>/edit/`. From there:

- **Add a car**: pick it and give a price — it becomes a new بند (line item), and
  **that car is also marked تم البيع** automatically.
- **Remove a بند**: allowed, except the last one — «لا يمكن حذف البند الوحيد في
  الفاتورة». To get rid of a one-item invoice you must delete the invoice itself,
  not the item.
- **Edit prices per بند**: the invoice total recalculates automatically from the
  items. The admin should not try to type a separate total — it is always the sum.

## Linking a customer account

On the edit page, the admin can attach a registered customer by typing their
**username or email**. If no match is found they'll see «لم يُعثر على حساب مطابق»
and the typed buyer fields are used instead — this is a warning, not a failure.

When an account is linked, **that account is the source of truth** and its name is
displayed on the invoice rather than the typed اسم المشتري. So if the name on a
printed invoice looks "wrong", check whether a customer account is attached — the
fix is to detach it or fix the account, not to retype اسم المشتري.

## Recording a payment (سند قبض)

Buyers commonly pay a عربون first and the rest later. Each payment gets its own
numbered, printable voucher.

From the invoice page, add a سند قبض with:

- **المبلغ المستلم** — must be greater than zero, or you get «أدخل مبلغاً صحيحاً».
- **الغرض** — عربون حجز السيارة / دفعة من قيمة السيارة / سداد باقي قيمة السيارة / أخرى.
- **طريقة الدفع** — حوالة بنكية / نقداً / شبكة أو بطاقة / شيك.
- **اسم المستلم**, **ملاحظة**, **التاريخ** (defaults to today).

The سند number is generated as `RCV-YYYYMMDD-00001` and is also locked. The receipt
prints the amount **in words** (تفقيط) automatically.

The invoice tracks **المدفوع** (sum of all سندات) and **المتبقي** (total minus paid)
on its own — the admin never types these.

A mistaken سند can be deleted, which returns to the invoice and the totals
recalculate.

### Important: مدفوعة is a manual checkbox

Recording سندات does **not** automatically tick **مدفوعة** on the invoice, even
when the receipts add up to the full amount. مدفوعة is only ever set by hand, via
the checkbox on the invoice create/edit form.

So if an admin asks why an invoice still shows unpaid after they recorded all the
payments: that's expected. Tell them to open the invoice edit page and tick
مدفوعة. المتبقي reaching zero and مدفوعة being ticked are two separate things.

## Contract

`/our-cars/<id>/invoice/<invoice_id>/contract/` — a printable عقد generated from
the invoice and buyer details. Nothing extra to fill in; it reads from the invoice.

## Shipment

`/our-cars/<id>/invoice/<invoice_id>/shipment/` — one shipment per invoice. The
first visit creates it; later visits edit the same one.

**الحالة**: قيد التجهيز (default) / تم التحميل / قيد الشحن / وصلت الميناء / تم التسليم / ملغي.

Other fields, all optional: شركة الشحن, اسم السفينة, رقم الحاوية, بوليصة الشحن,
ميناء الشحن, ميناء الوصول, دولة الوصول, تاريخ المغادرة المتوقع (ETD), تاريخ الوصول
المتوقع (ETA), تاريخ التسليم, تكلفة الشحن, رابط التتبع, ملاحظات.

## Public tracking — what the buyer sees

`/track/<رقم الفاتورة>/` is **public — no login**. The buyer reads the invoice
number off their printed invoice and follows the link to see shipment status and
ETA.

It deliberately shows **only** the car and the shipment status/dates. It does
**not** show prices, buyer personal details, or notes. If an admin worries that
customers can see private information through this link: they cannot — only what
the buyer already knows.

Each tenant's page is scoped to their own site, so one site's invoice number never
resolves on another site.

## Where sold cars live

Sold cars are listed at `/sold-cars/`. Since creating an invoice marks the car تم
البيع automatically, cars appear there once billed.

## Permissions

All of the above needs the `sales` section. A staff member with `cars` but not
`sales` can add and edit cars but cannot open invoices, receipts, contracts, or
shipments. Only the site admin can grant `sales`, from the staff page.
