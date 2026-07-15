# Dashboard guide: Ratings, questions & FAQ (section key: `reviews`)

Needs the `reviews` section. Three **separate, unrelated** systems live here, and
two of them have confusingly similar Arabic names:

| Dashboard tile | What it is |
|---|---|
| **التقييمات** | Customer star ratings awaiting moderation. |
| **الأسئلة الشائعة** | The public FAQ page at `/faq/`. |
| **الأسئلة** | A separate internal questions list — see the warning at the end. |

Answering something under **الأسئلة** does **not** put it on the public FAQ page.
Those are different systems. This trips up almost everyone.

---

## التقييمات — customer ratings

Path: `/staff/ratings/`. Tabs: **قيد المراجعة** (default), **موافق عليها**, **الكل**.

**Nothing a customer submits appears on the site until you approve it.** Every new
rating arrives unapproved. The public homepage shows only approved ratings, and the
star average is calculated from approved ones only.

Anyone can rate the site — including visitors who aren't logged in, who show as
**(زائر)**. There is no limit on visitor ratings, so moderation is the only thing
standing between the site and spam. Worth reviewing regularly.

Two buttons per row:

- **موافق** — publishes it. It appears on the homepage immediately.
- **رفض** — see the warning.

### ⚠️ رفض permanently deletes the rating

**رفض does not hide or flag the rating — it deletes it forever.** There is no
"rejected" list, no archive, no undo. On this page it does not even ask for
confirmation first: one click and the rating is gone.

The same applies to **حذف** on an already-approved rating.

If an admin asks how to get a rejected rating back, the honest answer is that it
cannot be recovered — the customer would have to submit it again. Tell people to
be careful with رفض, because the click is instant and final.

### A customer editing their rating un-publishes it

If a customer changes a rating you already approved — even just tweaking the
comment — it silently drops back to unapproved and disappears from the homepage
until you approve it again. Nothing notifies you.

So if an admin says "a review vanished from our homepage", this is the usual
reason: check **قيد المراجعة** and it's probably sitting there.

### A note on the numbers

The rating count shown on the dashboard includes ratings still awaiting approval,
while the average is calculated from approved ones only. So the count and the
average don't necessarily describe the same set. That's expected, not a fault.

---

## الأسئلة الشائعة — the public FAQ

Path: `/faq/manage/`. The public page is `/faq/`, and the first few entries also
appear on the homepage. **عرض الصفحة ↗** opens the public view.

Two ways an entry gets here:

**1. You add it.** Fill **السؤال** and **الإجابة**, then **إضافة (منشور)**. As the
button says, this **publishes immediately** — it goes live on `/faq/` and the
homepage at once. There is no draft option, so don't add a half-written answer
intending to finish it later.

**2. A visitor asks it.** The public FAQ page has an ask box. Those arrive under
**قيد المراجعة**, unpublished and invisible to the public, tagged **سؤال من زائر**
with the name they typed. The visitor is told their question will appear once an
admin reviews and answers it.

For a pending visitor question: write the **الإجابة**, make sure **نشر** is ticked,
and press **حفظ**.

### ⚠️ The نشر checkbox always looks ticked

On the **قيد المراجعة** list, the **نشر** checkbox appears ticked even though the
item is **not** published. It does not reflect the real state.

That means pressing **حفظ** on a pending question publishes it — which is usually
what you want, but it also means you cannot casually save a draft. To keep
something unpublished you have to untick a box that was showing the wrong state to
begin with.

If an admin says "I only pressed حفظ and it went live" — that's why. It's the
checkbox misleading them, not something they did wrong.

### حفظ with an empty answer wipes the answer

The answer box overwrites whatever was stored, so saving with it empty erases the
existing answer. Nothing stops you publishing a question with a blank answer, and
the public page will then show the question with nothing under it.

### الترتيب — lower numbers come first

**الترتيب** sorts **ascending**: 1 appears above 2. It is not "higher number =
higher up".

It defaults to **0**, so every entry left at the default ties, and ties fall back
to newest-first — meaning a newly added FAQ jumps to the top of the public page.
To control the order, give entries explicit numbers.

**حذف** removes an FAQ entry permanently (it does ask for confirmation here).

---

## الأسئلة — the internal questions list

Path: `/staff/questions/`. Tabs: **بدون إجابة**, **تمت الإجابة**, **الكل**.

**This list has no way to receive new questions.** There is no form anywhere on the
public site that creates one, so for most sites this page is simply empty and stays
empty. Customers asking questions go through **الأسئلة الشائعة** instead.

If there are old entries here and an admin answers one, be honest about what that
does: the answer is saved and the row is marked **تمت الإجابة**, but

- the customer is **not** notified, even though the confirmation says «تم إرسال الإجابة»,
- and the answer is **not** shown anywhere on the public site.

So the answer is only ever visible inside this dashboard. If an admin wants a
customer to actually receive an answer, they need to contact them directly, or use
**الأسئلة الشائعة** if it's a general question worth publishing.
