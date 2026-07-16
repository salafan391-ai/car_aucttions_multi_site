from django.contrib import messages
from site_cars.permissions import site_admin_required
from django.core.files.storage import default_storage
from django.db import OperationalError, ProgrammingError, connection
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from site_cars.models import SiteCar

from .forms import SECTION_META, PageForm, SectionForm
from .models import Page, PageSection


def _apply_gallery_images(request, section):
    """Update a gallery section's config.images from the upload form: drop the
    ones ticked for removal, append newly uploaded files."""
    cfg = dict(section.config or {})
    images = list(cfg.get("images") or [])
    remove = set(request.POST.getlist("remove_image"))
    images = [im for i, im in enumerate(images) if str(i) not in remove]
    for f in request.FILES.getlist("gallery_images"):
        saved = default_storage.save(f"site_builder/sections/{f.name}", f)
        images.append({"src": default_storage.url(saved)})
    cfg["images"] = images
    section.config = cfg


def _attach_section_data(sections):
    """For featured_cars / brand_strip sections, attach the queryset they need.

    Each section's `config` JSON drives the query. Examples:
      featured_cars: {"limit": 8, "manufacturer": "bmw", "is_featured": true, "status": "available"}
      brand_strip:   {"manufacturers": ["bmw", "mercedes-benz", "kia"]}
    """
    for s in sections:
        cfg = s.config or {}
        if s.type == PageSection.TYPE_FEATURED_CARS:
            qs = SiteCar.objects.all()
            if cfg.get("status"):
                qs = qs.filter(status=cfg["status"])
            else:
                qs = qs.filter(status="available")
            if cfg.get("is_featured"):
                qs = qs.filter(is_featured=True)
            for field in ("manufacturer", "model", "fuel", "transmission", "body_type"):
                value = cfg.get(field)
                if value:
                    qs = qs.filter(**{f"{field}__iexact": value})
            limit = int(cfg.get("limit", 8))
            s.cars = list(qs.order_by("-is_featured", "-created_at")[:limit])
        elif s.type == PageSection.TYPE_BRAND_STRIP:
            manufacturers = cfg.get("manufacturers") or []
            s.brand_items = [{"name": m} for m in manufacturers if m]
    return sections


@require_GET
def page_view(request, slug):
    try:
        page = Page.objects.get(slug=slug)
    except Page.DoesNotExist:
        raise Http404("Page not found")

    # Drafts (unpublished) are previewable by staff only; visitors get a 404.
    if not page.is_published and not request.user.is_staff:
        raise Http404("Page not found")

    sections = list(page.sections.filter(is_visible=True).order_by("order", "id"))
    _attach_section_data(sections)

    return render(
        request,
        "site_builder/page.html",
        {"page": page, "sections": sections},
    )


@require_GET
def home_view(request):
    """Render the Page with kind='home' if one exists; otherwise 404 so the
    project's existing home view at the same URL can take precedence in URL order."""
    response = render_home_if_configured(request)
    if response is None:
        raise Http404("No site_builder home page configured")
    return response


def render_home_if_configured(request):
    """If a published Page(kind='home') exists for the current tenant, render it
    and return the response. Otherwise return None so callers can fall through.

    Defensive against missing tables (public schema, fresh tenant pre-migration)."""
    try:
        page = Page.objects.get(kind=Page.KIND_HOME, is_published=True)
    except (Page.DoesNotExist, ProgrammingError, OperationalError):
        return None
    sections = list(page.sections.filter(is_visible=True).order_by("order", "id"))
    _attach_section_data(sections)
    return render(
        request,
        "site_builder/page.html",
        {"page": page, "sections": sections},
    )


# ──────────────────────────────────────────────────────────────────────────
# Dashboard page-builder editor (staff-only, tenant schemas only)
# ──────────────────────────────────────────────────────────────────────────
def _builder_link_options():
    """Friendly link targets for CTA dropdowns: core pages + builder pages."""
    from tenants.views import friendly_page_links
    links = list(friendly_page_links())
    try:
        for p in Page.objects.filter(is_published=True).order_by("title"):
            links.append({"label": f"📄 {p.title}", "url": f"/p/{p.slug}/"})
    except (ProgrammingError, OperationalError):
        pass
    return links


def _guard(request):
    """Return a redirect response if not usable here, else None."""
    if getattr(connection, "schema_name", "public") == "public":
        messages.error(request, "منشئ الصفحات متاح داخل مواقع المستأجرين فقط.")
        return redirect("home")
    return None


@site_admin_required
def pages_list(request):
    guard = _guard(request)
    if guard:
        return guard
    pages = Page.objects.all().order_by("nav_order", "title")
    return render(request, "site_builder/dashboard/pages_list.html", {"pages": pages})


@site_admin_required
def page_create(request):
    guard = _guard(request)
    if guard:
        return guard
    if request.method == "POST":
        form = PageForm(request.POST)
        if form.is_valid():
            page = form.save()
            messages.success(request, "تم إنشاء الصفحة. أضف الأقسام الآن.")
            return redirect("site_builder:page_edit", pk=page.pk)
    else:
        form = PageForm()
    return render(request, "site_builder/dashboard/page_form.html", {"form": form, "is_new": True})


@site_admin_required
def page_settings(request, pk):
    guard = _guard(request)
    if guard:
        return guard
    page = get_object_or_404(Page, pk=pk)
    if request.method == "POST":
        form = PageForm(request.POST, instance=page)
        if form.is_valid():
            form.save()
            messages.success(request, "تم حفظ إعدادات الصفحة.")
            return redirect("site_builder:page_edit", pk=page.pk)
    else:
        form = PageForm(instance=page)
    return render(request, "site_builder/dashboard/page_form.html", {"form": form, "page": page, "is_new": False})


@site_admin_required
def page_edit(request, pk):
    """Manage a page's sections (add / reorder / edit / delete)."""
    guard = _guard(request)
    if guard:
        return guard
    page = get_object_or_404(Page, pk=pk)
    sections = page.sections.order_by("order", "id")
    return render(request, "site_builder/dashboard/page_edit.html", {
        "page": page, "sections": sections, "section_meta": SECTION_META,
    })


@site_admin_required
@require_POST
def page_delete(request, pk):
    guard = _guard(request)
    if guard:
        return guard
    page = get_object_or_404(Page, pk=pk)
    page.delete()
    messages.success(request, "تم حذف الصفحة.")
    return redirect("site_builder:pages_list")


@site_admin_required
def section_edit(request, pk, sec_pk=None):
    guard = _guard(request)
    if guard:
        return guard
    page = get_object_or_404(Page, pk=pk)
    section = get_object_or_404(PageSection, pk=sec_pk, page=page) if sec_pk else None
    if request.method == "POST":
        form = SectionForm(request.POST, request.FILES, instance=section)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.page = page
            if section is None:
                obj.order = (page.sections.count())
            if obj.type == "gallery":
                _apply_gallery_images(request, obj)
            obj.save()
            messages.success(request, "تم حفظ القسم.")
            return redirect("site_builder:page_edit", pk=page.pk)
    else:
        initial = {}
        if section is None and request.GET.get("type") in SECTION_META:
            initial["type"] = request.GET.get("type")
        form = SectionForm(instance=section, initial=initial)
    return render(request, "site_builder/dashboard/section_form.html", {
        "form": form, "page": page, "section": section,
        "link_options": _builder_link_options(), "section_meta": SECTION_META,
    })


@site_admin_required
@require_POST
def section_delete(request, pk, sec_pk):
    guard = _guard(request)
    if guard:
        return guard
    section = get_object_or_404(PageSection, pk=sec_pk, page__pk=pk)
    section.delete()
    messages.success(request, "تم حذف القسم.")
    return redirect("site_builder:page_edit", pk=pk)


@site_admin_required
@require_POST
def section_move(request, pk, sec_pk, direction):
    guard = _guard(request)
    if guard:
        return guard
    page = get_object_or_404(Page, pk=pk)
    sections = list(page.sections.order_by("order", "id"))
    idx = next((i for i, s in enumerate(sections) if s.pk == int(sec_pk)), None)
    if idx is not None:
        swap = idx - 1 if direction == "up" else idx + 1
        if 0 <= swap < len(sections):
            sections[idx], sections[swap] = sections[swap], sections[idx]
            for i, s in enumerate(sections):
                if s.order != i:
                    PageSection.objects.filter(pk=s.pk).update(order=i)
    return redirect("site_builder:page_edit", pk=pk)
