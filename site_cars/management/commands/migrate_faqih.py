"""One-off migration: pull the old standalone alfaqihcars app's data (live
Heroku Postgres) into the `alfaqihcars` tenant schema here.

Scope (decided with the owner):
  - all users              core_customuser  -> auth.User + UserProfile
  - SOLD cars only         core_car(status=sold) -> SiteCar (status=sold)
  - car photos             referenced by URL (old S3 / auction hotlinks)
  - bills + orders         core_bill / core_order -> SiteBill (+ items)
  - shipments              core_carshippingtracker -> SiteShipment
  - ratings                core_rating -> SiteRating

Idempotent: rerunnable. Keyed on stable external ids (username, faqih_<car_id>,
FIC-B<bill_id> / FIC-O<order_id>). Use --dry-run first (does everything inside a
transaction and rolls back, printing the counts).

Run on Railway so writes hit the tenant DB, passing the source DSN + S3 base:
  railway ssh --service web "/opt/venv/bin/python manage.py migrate_faqih \
      --source-dsn '<heroku postgres url>' --dry-run"
"""
import re
from urllib.parse import quote

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_tenants.utils import schema_context


SHIP_STATUS = {
    "awaiting_shipment": "preparing",
    "shipped": "loaded",
    "expected_arrival": "in_transit",
    "customs_processing": "in_transit",
    "customs_cleared": "arrived",
    "delivered_to_carrier": "delivered",
}


def _int(v, default=None):
    if v is None or v == "":
        return default
    m = re.search(r"-?\d+", str(v))
    return int(m.group()) if m else default


class Command(BaseCommand):
    help = "Migrate the old alfaqihcars app data into the alfaqihcars tenant schema."

    def add_arguments(self, parser):
        parser.add_argument("--source-dsn", required=True, help="Old app's Postgres DSN (Heroku DATABASE_URL).")
        parser.add_argument("--schema", default="alfaqihcars")
        parser.add_argument("--s3-base", default="https://alfaqih.s3.us-west-2.amazonaws.com",
                            help="Base URL for old S3 image keys that have no image_url.")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=0, help="Cap sold cars processed (debug).")

    def handle(self, *args, **o):
        schema = o["schema"]
        if schema == "public":
            raise CommandError("Refusing to run against the public schema.")
        from tenants.models import Tenant
        if not Tenant.objects.filter(schema_name=schema).exists():
            raise CommandError(f"Tenant '{schema}' does not exist.")

        import psycopg2
        import psycopg2.extras
        dsn = o["source_dsn"]
        if "sslmode=" not in dsn:
            dsn += ("&" if "?" in dsn else "?") + "sslmode=require"
        src = psycopg2.connect(dsn)
        src.set_session(readonly=True)
        cur = src.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        self.s3_base = o["s3_base"].rstrip("/")
        self.stats = {}
        try:
            with schema_context(schema):
                with transaction.atomic():
                    umap = self._users(cur)
                    cmap = self._cars(cur, o["limit"])
                    self._images(cur, cmap)
                    bmap = self._bills(cur, umap, cmap)
                    self._shipments(cur, bmap)
                    self._ratings(cur, umap)
                    if o["dry_run"]:
                        self.stdout.write(self.style.WARNING("\nDRY RUN — rolling back."))
                        transaction.set_rollback(True)
        finally:
            cur.close()
            src.close()

        self.stdout.write(self.style.SUCCESS("\n=== migrate_faqih summary ==="))
        for k, v in self.stats.items():
            self.stdout.write(f"  {k}: {v}")
        if o["dry_run"]:
            self.stdout.write(self.style.WARNING("Nothing was written (dry run)."))

    # ── image URL resolution ────────────────────────────────────────────
    def _img_url(self, image, image_url):
        if image_url and str(image_url).strip():
            return str(image_url).strip()
        if image and str(image).strip():
            return f"{self.s3_base}/{quote(str(image).strip())}"
        return ""

    # ── users ───────────────────────────────────────────────────────────
    def _users(self, cur):
        from django.contrib.auth import get_user_model
        from site_cars.models import UserProfile
        User = get_user_model()
        cur.execute("""SELECT id, username, email, password, is_staff, is_superuser,
            is_active, date_joined, last_login, full_name, phone_number, identity_number, city
            FROM core_customuser""")
        rows = cur.fetchall()
        umap, created, updated = {}, 0, 0
        seen = set()
        for r in rows:
            uname = (r["username"] or "").strip() or (r["email"] or "").strip() or f"faqih_{r['id']}"
            uname = uname[:150]
            # de-dup usernames across the batch (old table is unique, but emails-as-fallback may clash)
            if uname in seen:
                uname = f"{uname[:140]}_{r['id']}"
            seen.add(uname)
            u, is_new = User.objects.get_or_create(username=uname)
            u.email = (r["email"] or "")[:254]
            u.password = r["password"] or "!"      # copy hash verbatim -> same password works
            u.is_staff = bool(r["is_staff"])
            u.is_superuser = bool(r["is_superuser"])
            u.is_active = bool(r["is_active"])
            if r["full_name"]:
                u.first_name = str(r["full_name"])[:150]
            if r["date_joined"]:
                u.date_joined = r["date_joined"]
            if r["last_login"]:
                u.last_login = r["last_login"]
            u.save()
            UserProfile.objects.update_or_create(user=u, defaults={
                "phone": (r["phone_number"] or "")[:30],
                "identity_number": (r["identity_number"] or "")[:20],
            })
            umap[r["id"]] = u
            created += is_new
            updated += (not is_new)
        self.stats["users_created"] = created
        self.stats["users_updated"] = updated
        return umap

    # ── sold cars ───────────────────────────────────────────────────────
    def _cars(self, cur, limit):
        from site_cars.models import SiteCar
        q = """SELECT c.id, c.car_id, c.price, c.year, c.mission, c.fuel, c.mileage,
                   c.power, c.body, c.wheel, c.description, c.status, c.auction_date,
                   b.name AS brand, m.name AS model, col.name AS color
            FROM core_car c
            JOIN core_model m ON m.id = c.model_id
            JOIN core_brand b ON b.id = m.brand_id
            LEFT JOIN core_color col ON col.id = c.color_id
            WHERE c.status = 'sold'
            ORDER BY c.id"""
        cur.execute(q)
        rows = cur.fetchall()
        if limit:
            rows = rows[:limit]
        cmap, created, updated = {}, 0, 0
        for r in rows:
            brand = (r["brand"] or "").strip()
            model = (r["model"] or "").strip()
            title = " ".join(x for x in [brand, model, str(r["year"] or "")] if x).strip()
            defaults = {
                "title": title[:200] or f"faqih {r['car_id']}",
                "manufacturer": brand[:100] or "unknown",
                "model": model[:100] or "unknown",
                "year": _int(r["year"], 0),
                "color": (r["color"] or "")[:100],
                "mileage": _int(r["mileage"], 0),
                "price": _int(r["price"], 0),
                "currency": "SAR",
                "transmission": (r["mission"] or "")[:100],
                "fuel": (r["fuel"] or "")[:100],
                "body_type": (r["body"] or "")[:100],
                "drive_wheel": (r["wheel"] or "")[:100],
                "engine": (str(r["power"]) if r["power"] else "")[:100],
                "engine_cc": _int(r["power"]),
                "description": r["description"] or "",
                "status": "sold",
                "auction_end": r["auction_date"],
            }
            obj, is_new = SiteCar.objects.update_or_create(
                external_id=f"faqih_{r['car_id']}"[:50], defaults=defaults)
            cmap[r["id"]] = obj
            created += is_new
            updated += (not is_new)
        self.stats["cars_created"] = created
        self.stats["cars_updated"] = updated
        return cmap

    # ── images (referenced by URL) ──────────────────────────────────────
    def _images(self, cur, cmap):
        from site_cars.models import SiteCar, SiteCarImage
        if not cmap:
            self.stats["images"] = 0
            return
        ids = list(cmap.keys())
        cur.execute("""SELECT car_id, image, image_url FROM core_carimage
            WHERE car_id = ANY(%s) ORDER BY car_id, id""", (ids,))
        by_car = {}
        for r in cur.fetchall():
            url = self._img_url(r["image"], r["image_url"])
            if url:
                by_car.setdefault(r["car_id"], []).append(url)
        total = 0
        for old_id, sc in cmap.items():
            urls = by_car.get(old_id, [])
            SiteCarImage.objects.filter(car=sc).delete()   # rebuild cleanly on rerun
            if urls:
                if not sc.external_image_url:
                    sc.external_image_url = urls[0][:500]
                    SiteCar.objects.filter(pk=sc.pk).update(external_image_url=sc.external_image_url)
                SiteCarImage.objects.bulk_create([
                    SiteCarImage(car=sc, image_url=u[:500], order=i) for i, u in enumerate(urls)
                ])
                total += len(urls)
        self.stats["images"] = total

    # ── bills (from core_bill, plus orders with no bill) ────────────────
    def _bills(self, cur, umap, cmap):
        from site_cars.models import SiteBill, SiteBillItem
        from datetime import date as _date
        bmap = {}          # old order_id -> SiteBill (for shipment attachment)
        created = 0
        # 1) real bills
        cur.execute("""SELECT b.id, b.order_id, b.buyer, b.price, b.recite_number,
                   b.date, b.is_paid, b.region, o.user_id, o.car_id
            FROM core_bill b JOIN core_order o ON o.id = b.order_id ORDER BY b.id""")
        for r in cur.fetchall():
            sc = cmap.get(r["car_id"])
            buyer_user = umap.get(r["user_id"])
            receipt = (r["recite_number"] or f"FIC-B{r['id']}")[:100]
            bill, _ = SiteBill.objects.update_or_create(receipt_number=receipt, defaults={
                "site_car": sc,
                "price": r["price"] or 0,
                "buyer_name": (r["buyer"] or "")[:200],
                "buyer_user": buyer_user,
                "date": r["date"] or _date.today(),
                "is_paid": bool(r["is_paid"]),
                "description": (r["region"] or "")[:255],
            })
            SiteBillItem.objects.filter(bill=bill).delete()
            SiteBillItem.objects.create(
                bill=bill, site_car=sc,
                title=(sc.title if sc else "")[:255], price=r["price"] or 0)
            bmap[r["order_id"]] = bill
            created += 1
        self.stats["bills_from_bills"] = created
        # 2) orders that produced no bill -> a bill from the order itself
        cur.execute("""SELECT o.id, o.user_id, o.car_id, o.offer_price, o.status,
                   o.notes, o.created_at
            FROM core_order o
            WHERE NOT EXISTS (SELECT 1 FROM core_bill b WHERE b.order_id = o.id)
            ORDER BY o.id""")
        order_bills = 0
        for r in cur.fetchall():
            sc = cmap.get(r["car_id"])
            buyer_user = umap.get(r["user_id"])
            receipt = f"FIC-O{r['id']}"
            bill, _ = SiteBill.objects.update_or_create(receipt_number=receipt, defaults={
                "site_car": sc,
                "price": r["offer_price"] or 0,
                "buyer_user": buyer_user,
                "buyer_name": (buyer_user.get_full_name() if buyer_user else "") or "",
                "date": (r["created_at"].date() if r["created_at"] else _date.today()),
                "is_paid": r["status"] == "completed",
                "description": (r["notes"] or "")[:255],
            })
            SiteBillItem.objects.filter(bill=bill).delete()
            SiteBillItem.objects.create(
                bill=bill, site_car=sc,
                title=(sc.title if sc else "")[:255], price=r["offer_price"] or 0)
            bmap.setdefault(r["id"], bill)
            order_bills += 1
        self.stats["bills_from_orders"] = order_bills
        return bmap

    # ── shipments ───────────────────────────────────────────────────────
    def _shipments(self, cur, bmap):
        from site_cars.models import SiteShipment
        cur.execute("""SELECT order_id, status, notes, tracking_code,
                   expected_arrival_date FROM core_carshippingtracker ORDER BY id""")
        made, skipped = 0, 0
        for r in cur.fetchall():
            bill = bmap.get(r["order_id"])
            if not bill:
                skipped += 1
                continue
            SiteShipment.objects.update_or_create(bill=bill, defaults={
                "status": SHIP_STATUS.get(r["status"], "preparing"),
                "container_number": (r["tracking_code"] or "")[:50],
                "eta": r["expected_arrival_date"],
                "notes": r["notes"] or "",
            })
            made += 1
        self.stats["shipments"] = made
        self.stats["shipments_skipped_no_bill"] = skipped

    # ── ratings ─────────────────────────────────────────────────────────
    def _ratings(self, cur, umap):
        from site_cars.models import SiteRating
        cur.execute("""SELECT user_id, rating, review, is_public FROM core_rating""")
        made = 0
        for r in cur.fetchall():
            u = umap.get(r["user_id"])
            if not u:
                continue
            SiteRating.objects.update_or_create(user=u, car=None, defaults={
                "rating": _int(r["rating"], 5),
                "comment": r["review"] or "",
                "is_approved": bool(r["is_public"]),
                "name": (u.get_full_name() or u.username)[:120],
            })
            made += 1
        self.stats["ratings"] = made
