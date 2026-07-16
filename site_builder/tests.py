import io

from django.contrib.auth.models import User
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient

from .forms import PageForm
from .models import Page, PageSection


def _png():
    # 1x1 PNG so the gallery upload path exercises real file storage.
    data = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    f = io.BytesIO(data)
    f.name = "g.png"
    return f


class BuilderTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        User.objects.create_user("owner", password="pw", is_staff=True, is_superuser=True)
        self.client.login(username="owner", password="pw")

    def _page(self, kind="custom", slug="p1"):
        return Page.objects.create(kind=kind, slug=slug, title="P")

    # ---- CTA: both buttons persist and render ----

    def test_cta_section_saves_both_buttons(self):
        page = self._page()
        r = self.client.post(f"/dashboard/pages/{page.pk}/sections/new/", {
            "type": "cta", "title": "اطلب", "is_visible": "on",
            "cta_label": "تصفح", "cta_url": "/cars/",
            "cta_label2": "تواصل", "cta_url2": "/contact/",
        })
        self.assertEqual(r.status_code, 302)
        sec = page.sections.get()
        self.assertEqual(sec.config["cta_label"], "تصفح")
        self.assertEqual(sec.config["cta_url2"], "/contact/")
        # renders on the public page
        page_html = self.client.get(f"/p/{page.slug}/").content.decode()
        self.assertIn("/cars/", page_html)
        self.assertIn("/contact/", page_html)

    # ---- Gallery: uploads populate config.images and render ----

    def test_gallery_upload_populates_images(self):
        page = self._page(slug="g")
        r = self.client.post(
            f"/dashboard/pages/{page.pk}/sections/new/",
            {"type": "gallery", "title": "معرض", "is_visible": "on", "gallery_images": _png()},
        )
        self.assertEqual(r.status_code, 302)
        sec = page.sections.get()
        self.assertEqual(len(sec.config.get("images", [])), 1)
        self.assertTrue(sec.config["images"][0]["src"])
        page_html = self.client.get(f"/p/{page.slug}/").content.decode()
        self.assertIn(sec.config["images"][0]["src"], page_html)

    def test_gallery_remove_image(self):
        page = self._page(slug="g2")
        sec = PageSection.objects.create(
            page=page, type="gallery", order=0,
            config={"images": [{"src": "/a.png"}, {"src": "/b.png"}]},
        )
        r = self.client.post(f"/dashboard/pages/{page.pk}/sections/{sec.pk}/", {
            "type": "gallery", "is_visible": "on", "remove_image": "0",
        })
        self.assertEqual(r.status_code, 302)
        sec.refresh_from_db()
        self.assertEqual([i["src"] for i in sec.config["images"]], ["/b.png"])

    # ---- kind: editable + singleton uniqueness ----

    def test_page_form_exposes_kind(self):
        self.assertIn("kind", PageForm().fields)

    def test_duplicate_singleton_kind_rejected(self):
        Page.objects.create(kind="home", slug="home", title="H")
        form = PageForm(data={"kind": "home", "title": "Home 2", "slug": "home2", "nav_order": 0})
        self.assertFalse(form.is_valid())
        self.assertIn("kind", form.errors)

    def test_duplicate_slug_rejected(self):
        Page.objects.create(kind="custom", slug="taken", title="T")
        form = PageForm(data={"kind": "custom", "title": "X", "slug": "taken", "nav_order": 0})
        self.assertFalse(form.is_valid())
        self.assertIn("slug", form.errors)

    def test_custom_kind_allows_multiple(self):
        Page.objects.create(kind="custom", slug="c1", title="C1")
        form = PageForm(data={"kind": "custom", "title": "C2", "slug": "c2", "nav_order": 0})
        self.assertTrue(form.is_valid(), form.errors)

    # ---- bg/align/width presets reach the rendered wrapper ----

    def test_section_presets_render_on_wrapper(self):
        page = self._page(slug="pw")
        PageSection.objects.create(
            page=page, type="text", order=0, title="T", body="hi",
            config={"bg": "dark", "align": "center", "width": "wide"},
        )
        html = self.client.get(f"/p/{page.slug}/").content.decode()
        self.assertIn("sb-bg-dark", html)
        self.assertIn("sb-align-center", html)
        self.assertIn("sb-w-wide", html)


class DraftPreviewTests(TenantTestCase):
    def setUp(self):
        self.client = TenantClient(self.tenant)
        self.page = Page.objects.create(kind="custom", slug="draft", title="D", is_published=False)
        PageSection.objects.create(page=self.page, type="text", order=0, title="hi", body="x")

    def test_anonymous_gets_404_for_unpublished(self):
        self.assertEqual(self.client.get("/p/draft/").status_code, 404)

    def test_staff_can_preview_unpublished(self):
        User.objects.create_user("owner", password="pw", is_staff=True, is_superuser=True)
        self.client.login(username="owner", password="pw")
        self.assertEqual(self.client.get("/p/draft/").status_code, 200)

    def test_published_still_public(self):
        self.page.is_published = True
        self.page.save()
        self.assertEqual(self.client.get("/p/draft/").status_code, 200)
