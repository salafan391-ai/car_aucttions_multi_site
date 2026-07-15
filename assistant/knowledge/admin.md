# Dashboard guide: Site-admin-only tools

Everything in this file is for the **site admin** (the owner of this site). Limited
staff cannot reach any of it — clicking one of these links gives them a bare
"403 / ليس لديك صلاحية" error page, not a friendly explanation. So if a staff
member reports a permission error on these, that's expected; only the site admin
can do it, and there is no toggle to grant it.

Note: imports, damaged-car bulk delete, and shareable collections are **not** in
this list — those need only the `cars` section. See the cars guide.

---

## الموظفون — staff accounts

Path: `/dashboard/staff/`.

**Adding a staff member**: username (required, cannot be changed later), password
(required), optionally email and first name, plus **at least one** section —
«اختر صلاحية واحدة على الأقل» if none are ticked. The four sections are:

- **السيارات والمخزون** — add/edit/delete cars, auctions, and imports.
- **الفواتير والإيصالات** — invoices, receipts, contracts, shipping.
- **طلبات العملاء** — view orders and change their status.
- **التقييمات والأسئلة** — approve ratings, answer questions, the FAQ.

The password is shown **in plain text on purpose** so the admin can copy it and
hand it to the employee — that's the note «كلمة المرور ظاهرة حتى تتمكن من نسخها
وتسليمها للموظف». There's a generator that avoids easily-confused characters. The
employee can change it later from their own account page.

**Things worth knowing:**

- **Username cannot be changed after creation.** The field is locked on the edit
  page. To change it, delete and re-create the account.
- **Deactivating is not deleting.** Untick «الحساب نشط» to block login while
  keeping the account and its history. **حذف** is permanent.
- **Site admins are not listed here as editable.** They appear in a read-only
  **مدراء الموقع** list. An admin cannot edit, deactivate, or delete themselves or
  another admin from this page — so it is impossible to lock yourself out here.
- **You cannot promote a staff member to admin.** There is no button for it; new
  admins are created through account setup, not this page. If someone asks how to
  make an employee a full admin, the honest answer is that this page can't.
- Unticking every section is rejected — an account must reach at least one.

Sections not listed above (site settings, the page builder, billing) cannot be
granted to staff at all: «إعدادات الموقع، المتجر، منشئ الصفحات، والفوترة متاحة
لمدير الموقع فقط ولا يمكن منحها للموظفين».

---

## إعدادات الموقع — site settings

Path: `/settings/`. This is the biggest page in the dashboard. It covers:

- **Identity** — site name, logo, favicon, hero image, font, and the brand colours
  (primary/secondary/accent), plus the theme.
- **Contact** — phone(s), WhatsApp, email, address, city, map link, working hours,
  contact person and photo — most with English variants.
- **Content** — tagline, about text, footer, SEO title/description/keywords, the
  news ticker (on/off, text, colour), and the "how we work" steps.
- **Social** — Instagram, X/Twitter, Facebook, TikTok, Snapchat, YouTube, Telegram,
  WhatsApp channel.
- **Commerce** — which catalogues appear (المزادات / Encar), section labels, price
  markup percent (0–100), custom currencies, the import-cost calculator, and the
  buyer contract details (bank, commission, clearance, port, stamp…).
- **Email (SMTP)** — host, port, username, password, TLS, sender name. Leaving the
  password blank keeps the existing one rather than clearing it.

Saving shows «تم حفظ الإعدادات بنجاح!».

**Things that surprise admins:**

- **Uploading a new logo, favicon, hero image, photo, or stamp deletes the old file
  immediately.** There is no history and no undo — keep your own copy first.
- **Repeatable lists are rebuilt on every save, not merged.** Phone numbers,
  salespeople, and the "how we work" steps get wiped and re-created from whatever
  the form submits. If the page didn't load fully, or something went wrong in the
  browser, saving can silently empty one of those lists. If an admin says their
  phone numbers or staff photos "disappeared after saving settings", this is why —
  they must be re-entered.
- SMTP matters more than it looks: if it isn't configured, order emails to
  customers silently fail while the customer still sees a success message.

**كلمة مرور لوحة التحكم** (`/settings/password/`) sets *your own* dashboard
password and works for any staff member, not just the admin.

---

## منشئ الصفحات — the page builder

Path: `/dashboard/pages/`. Build extra pages that live at `/p/<slug>/`.

**Flow**: create the page → «تم إنشاء الصفحة. أضف الأقسام الآن.» → add sections one
at a time → **معاينة ↗** to view it.

**Section types**: بانر رئيسي (Hero), نص / فقرة, دعوة لإجراء (CTA), سيارات مختارة,
معرض صور, شريط الماركات, نموذج تواصل, HTML مخصّص. Each can be styled (default /
light / brand / dark background, start-aligned or centred, normal / wide / full
width). New sections are added at the end; use the move buttons to reorder.

**Two gotchas:**

- **A new page is published the moment you create it.** It's live at its address
  straight away, before you've added a single section — a visitor with the link
  would see an empty page. If you want to work on it privately, untick the publish
  option first; the list shows it as **مسودة**.
- **Publishing and appearing in the menu are two different switches.** A published
  page is reachable by link but does not appear in the site navigation unless you
  also turn on the "show in nav" option.

Note the page settings form labels are in **English** (Title, Slug, Meta
description, Is published, Show in nav, Nav order) even though the rest of the
dashboard is Arabic. The section form is in Arabic. That's a known inconsistency,
not a broken page.

**حذف** a page deletes all of its sections with it, permanently.

---

## تيليجرام — Telegram

Connect the dealership's own Telegram chat once via **ربط تيليجرام**, which opens
the bot; once linked the dashboard shows **متصل بتيليجرام**. After that,
**إرسال إلى تيليجرام** pushes the cars in the share cart (up to 60) to that chat,
one message per car with its photo.

Only the site admin can link or send, even though a staff member with `cars` can
open the cart and see the button.

---

## الفوترة — billing

Path: `/billing/`. Only appears when billing is enabled for the site.

Shows the amount due and the subscription status, with a button that sends the
admin to Stripe to pay. **Each payment adds a flat 30 days**, and paying early
stacks onto the remaining time rather than resetting it.

Nothing auto-renews and there is no cancel button — access simply lapses when the
paid period ends. Payment links and generic invoices are platform-owner tools; a
site admin never sees them.

---

## إرسال بريد — sending email

Path: `/send-email/`. Two modes:

- **Single** — one recipient; you get «تم إرسال البريد إلى …», or «فشل إرسال
  البريد. تحقق من إعدادات SMTP.» if SMTP is wrong.
- **Broadcast** — ⚠️ this emails **every registered user on the site who has an
  email address**, customers included. There is **no confirmation dialog** and no
  way to unsend. Anyone asking about broadcast should be told plainly what it does
  before they press it.

The page shows the last 20 emails sent and whether each succeeded — the place to
check when someone says an email never arrived.

Requires working SMTP under site settings; without it, sending fails.

---

## الرسائل — inbox

`/inbox/` is **not** admin-only — every logged-in user has one, customers included.
Staff can message any user; customers can only message staff. Opening a message
marks it read, and replying prefixes the subject with «رد:».
