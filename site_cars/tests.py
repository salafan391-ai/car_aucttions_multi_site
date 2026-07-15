from django.contrib.auth.models import AnonymousUser, User
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient

from .models import StaffAccess
from .permissions import (
    allowed_sections,
    has_section,
    is_site_admin,
    section_required,
    site_admin_required,
    staff_required,
)


class PermissionHelperTests(TenantTestCase):
    """The tier rules in site_cars.permissions, exercised inside a tenant schema."""

    def setUp(self):
        self.admin = User.objects.create_user(
            "owner", password="x", is_staff=True, is_superuser=True
        )
        self.staff = User.objects.create_user("seller", password="x", is_staff=True)
        StaffAccess.objects.create(user=self.staff, can_cars=True)
        self.customer = User.objects.create_user("buyer", password="x")

    def test_site_admin_reaches_every_section(self):
        self.assertTrue(is_site_admin(self.admin))
        self.assertEqual(
            allowed_sections(self.admin), {"cars", "sales", "orders", "reviews"}
        )

    def test_limited_staff_reaches_only_ticked_sections(self):
        self.assertFalse(is_site_admin(self.staff))
        self.assertEqual(allowed_sections(self.staff), {"cars"})
        self.assertTrue(has_section(self.staff, "cars"))
        self.assertFalse(has_section(self.staff, "sales"))

    def test_has_section_is_an_or_across_sections(self):
        self.assertTrue(has_section(self.staff, "sales", "cars"))
        self.assertFalse(has_section(self.staff, "sales", "orders"))

    def test_customer_reaches_nothing(self):
        self.assertEqual(allowed_sections(self.customer), frozenset())

    def test_staff_without_an_access_row_reaches_nothing(self):
        """Default-deny: the is_staff flag alone must not grant access."""
        orphan = User.objects.create_user("orphan", password="x", is_staff=True)
        self.assertEqual(allowed_sections(orphan), frozenset())

    def test_unticking_a_section_revokes_it(self):
        self.staff.staff_access.can_cars = False
        self.staff.staff_access.save()
        self.staff.refresh_from_db()
        self.assertEqual(allowed_sections(self.staff), frozenset())

    def test_section_required_rejects_unknown_keys(self):
        with self.assertRaises(ValueError):
            section_required("nonexistent")


class DecoratorTests(TenantTestCase):
    """The decorators themselves: allow, 403, or bounce to login."""

    def setUp(self):
        self.factory = RequestFactory()
        self.admin = User.objects.create_user(
            "owner", password="x", is_staff=True, is_superuser=True
        )
        self.staff = User.objects.create_user("seller", password="x", is_staff=True)
        StaffAccess.objects.create(user=self.staff, can_cars=True)

    @staticmethod
    def _ok(request):
        return "reached"

    def _call(self, view, user):
        request = self.factory.get("/dashboard/")
        request.user = user
        return view(request)

    def test_section_required_allows_a_granted_section(self):
        view = section_required("cars")(self._ok)
        self.assertEqual(self._call(view, self.staff), "reached")

    def test_section_required_blocks_an_ungranted_section(self):
        view = section_required("sales")(self._ok)
        with self.assertRaises(PermissionDenied):
            self._call(view, self.staff)

    def test_section_required_always_allows_the_site_admin(self):
        view = section_required("sales")(self._ok)
        self.assertEqual(self._call(view, self.admin), "reached")

    def test_site_admin_required_blocks_limited_staff(self):
        view = site_admin_required(self._ok)
        with self.assertRaises(PermissionDenied):
            self._call(view, self.staff)

    def test_staff_required_allows_any_dashboard_account(self):
        view = staff_required(self._ok)
        self.assertEqual(self._call(view, self.staff), "reached")
        self.assertEqual(self._call(view, self.admin), "reached")

    def test_anonymous_is_redirected_to_the_site_login(self):
        """staff_member_required bounced to the admin login, which
        BlockTenantAdminMiddleware 404s on a tenant domain. Ours must not."""
        view = section_required("cars")(self._ok)
        response = self._call(view, AnonymousUser())
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("/admin/", response["Location"])


class StaffManagementViewTests(TenantTestCase):
    """End-to-end: the admin's staff screens, and who may reach them."""

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.admin = User.objects.create_user(
            "owner", password="adminpass123", is_staff=True, is_superuser=True
        )
        self.staff = User.objects.create_user(
            "seller", password="staffpass123", is_staff=True
        )
        StaffAccess.objects.create(user=self.staff, can_cars=True)

    def test_limited_staff_cannot_open_staff_management(self):
        self.client.login(username="seller", password="staffpass123")
        self.assertEqual(self.client.get("/dashboard/staff/").status_code, 403)

    def test_limited_staff_cannot_create_staff(self):
        """The dangerous one: privilege escalation via the add form."""
        self.client.login(username="seller", password="staffpass123")
        response = self.client.post(
            "/dashboard/staff/add/",
            {"username": "mole", "password": "Sup3rSecret!x", "section_cars": "on"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="mole").exists())

    def test_admin_creates_staff_with_only_the_ticked_sections(self):
        self.client.login(username="owner", password="adminpass123")
        response = self.client.post(
            "/dashboard/staff/add/",
            {
                "username": "newbie",
                "email": "newbie@example.com",
                "password": "Str0ngPassw0rd!",
                "section_orders": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        created = User.objects.get(username="newbie")
        self.assertTrue(created.is_staff)
        self.assertFalse(created.is_superuser)
        self.assertEqual(allowed_sections(created), {"orders"})

    def test_created_staff_can_log_in_with_the_given_password(self):
        self.client.login(username="owner", password="adminpass123")
        self.client.post(
            "/dashboard/staff/add/",
            {"username": "newbie", "password": "Str0ngPassw0rd!", "section_orders": "on"},
        )
        self.client.logout()
        self.assertTrue(self.client.login(username="newbie", password="Str0ngPassw0rd!"))

    def test_creating_staff_requires_at_least_one_section(self):
        self.client.login(username="owner", password="adminpass123")
        response = self.client.post(
            "/dashboard/staff/add/",
            {"username": "nobody", "password": "Str0ngPassw0rd!"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="nobody").exists())

    def test_creating_staff_rejects_a_weak_password(self):
        self.client.login(username="owner", password="adminpass123")
        self.client.post(
            "/dashboard/staff/add/",
            {"username": "weak", "password": "123", "section_cars": "on"},
        )
        self.assertFalse(User.objects.filter(username="weak").exists())

    def test_creating_staff_rejects_a_duplicate_username(self):
        self.client.login(username="owner", password="adminpass123")
        self.client.post(
            "/dashboard/staff/add/",
            {"username": "seller", "password": "Str0ngPassw0rd!", "section_cars": "on"},
        )
        self.assertEqual(User.objects.filter(username="seller").count(), 1)

    def test_admin_edits_sections(self):
        self.client.login(username="owner", password="adminpass123")
        response = self.client.post(
            f"/dashboard/staff/{self.staff.pk}/edit/",
            {"section_sales": "on", "is_active": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.staff.refresh_from_db()
        self.assertEqual(allowed_sections(self.staff), {"sales"})

    def test_admin_cannot_reach_another_admin_through_the_staff_screens(self):
        """These screens manage limited staff only — admins aren't targets."""
        other_admin = User.objects.create_user(
            "owner2", password="x", is_staff=True, is_superuser=True
        )
        self.client.login(username="owner", password="adminpass123")
        response = self.client.get(f"/dashboard/staff/{other_admin.pk}/edit/")
        self.assertEqual(response.status_code, 404)

    def test_admin_deletes_staff(self):
        self.client.login(username="owner", password="adminpass123")
        response = self.client.post(f"/dashboard/staff/{self.staff.pk}/delete/")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(username="seller").exists())

    def test_staff_delete_rejects_get(self):
        self.client.login(username="owner", password="adminpass123")
        self.assertEqual(
            self.client.get(f"/dashboard/staff/{self.staff.pk}/delete/").status_code, 405
        )
        self.assertTrue(User.objects.filter(username="seller").exists())

    def test_admin_sees_the_staff_list(self):
        self.client.login(username="owner", password="adminpass123")
        response = self.client.get("/dashboard/staff/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "seller")

    def test_add_form_renders_a_checkbox_per_section(self):
        self.client.login(username="owner", password="adminpass123")
        response = self.client.get("/dashboard/staff/add/")
        self.assertEqual(response.status_code, 200)
        for key in ("cars", "sales", "orders", "reviews"):
            self.assertContains(response, f'name="section_{key}"')

    def test_edit_form_pre_ticks_the_current_sections(self):
        self.client.login(username="owner", password="adminpass123")
        response = self.client.get(f"/dashboard/staff/{self.staff.pk}/edit/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="section_cars" checked')
        self.assertNotContains(response, 'name="section_sales" checked')

    def test_password_suggestion_is_admin_only(self):
        self.client.login(username="seller", password="staffpass123")
        self.assertEqual(
            self.client.get("/dashboard/staff/password-suggestion/").status_code, 403
        )
        self.client.login(username="owner", password="adminpass123")
        response = self.client.get("/dashboard/staff/password-suggestion/")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()["password"]), 12)


class GatedViewTests(TenantTestCase):
    """A limited staff member hitting real dashboard views."""

    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.staff = User.objects.create_user(
            "seller", password="staffpass123", is_staff=True
        )
        StaffAccess.objects.create(user=self.staff, can_orders=True)
        self.client.login(username="seller", password="staffpass123")

    def test_reaches_a_granted_section(self):
        self.assertEqual(self.client.get("/staff/orders/").status_code, 200)

    def test_blocked_from_an_ungranted_section(self):
        self.assertEqual(self.client.get("/our-cars/add/").status_code, 403)

    def test_blocked_from_site_settings(self):
        self.assertEqual(self.client.get("/settings/").status_code, 403)

    def test_dashboard_hides_ungranted_tiles(self):
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/staff/orders/")
        self.assertNotContains(response, "/dashboard/staff/")

    def test_dashboard_hides_revenue_from_staff_without_sales(self):
        response = self.client.get("/dashboard/")
        self.assertNotContains(response, "إجمالي الإيرادات")

    def test_dashboard_shows_revenue_to_the_site_admin(self):
        User.objects.create_user(
            "owner", password="adminpass123", is_staff=True, is_superuser=True
        )
        self.client.login(username="owner", password="adminpass123")
        response = self.client.get("/dashboard/")
        self.assertContains(response, "إجمالي الإيرادات")
