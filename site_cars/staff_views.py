"""Staff management for a site admin: list, create, edit and remove the limited
staff accounts of the current tenant.

Everything here runs inside the tenant schema, so ``User`` is the tenant's own
``auth_user`` table — creating an account here has no effect on any other site.
"""
import secrets
import string

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django_tenants.utils import get_public_schema_name

from .models import StaffAccess
from .permissions import SECTIONS, SECTION_FIELDS, SECTION_KEYS, site_admin_required


def _require_tenant_schema():
    """Staff accounts are per-site; the platform schema has no staff to manage."""
    if connection.schema_name == get_public_schema_name():
        raise Http404("Staff management is only available on a site.")


def _staff_queryset():
    """Limited staff of this site — admins are excluded; they manage, not managed."""
    return (
        User.objects.filter(is_staff=True, is_superuser=False)
        .select_related("staff_access")
        .order_by("username")
    )


def _sections_from_post(request):
    """Read the ticked section checkboxes, keyed by section key."""
    return {key: bool(request.POST.get(f"section_{key}")) for key in SECTION_KEYS}


def _as_access_fields(sections):
    """Section-key dict -> ``StaffAccess`` field kwargs."""
    return {SECTION_FIELDS[key]: value for key, value in sections.items()}


def _section_rows(sections):
    """Checkbox rows for the form — Django templates can't index a dict by a
    variable key, so resolve ``checked`` here."""
    return [
        {"key": key, "label": label, "help": help_text, "checked": sections.get(key, False)}
        for key, label, help_text in SECTIONS
    ]


def _generate_password(length=14):
    # Ambiguous glyphs removed — these passwords get read off a screen and typed.
    alphabet = (string.ascii_letters + string.digits).translate(
        str.maketrans("", "", "lIO01")
    )
    return "".join(secrets.choice(alphabet) for _ in range(length))


@site_admin_required
def staff_list(request):
    _require_tenant_schema()
    staff = list(_staff_queryset())
    for member in staff:
        access = getattr(member, "staff_access", None)
        member.granted_labels = [
            label for key, label, _help in SECTIONS
            if access and getattr(access, SECTION_FIELDS[key])
        ]
    return render(request, "site_cars/staff_list.html", {
        "staff": staff,
        "admins": User.objects.filter(is_staff=True, is_superuser=True).order_by("username"),
    })


@site_admin_required
def staff_add(request):
    _require_tenant_schema()
    form = {"username": "", "email": "", "first_name": ""}
    sections = {key: False for key in SECTION_KEYS}

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        email = (request.POST.get("email") or "").strip()
        first_name = (request.POST.get("first_name") or "").strip()
        password = request.POST.get("password") or ""
        sections = _sections_from_post(request)
        form = {"username": username, "email": email, "first_name": first_name}

        errors = []
        if not username:
            errors.append("اسم المستخدم مطلوب.")
        elif User.objects.filter(username__iexact=username).exists():
            errors.append("اسم المستخدم مستخدم بالفعل.")
        if email and User.objects.filter(email__iexact=email).exists():
            errors.append("البريد الإلكتروني مستخدم بالفعل.")
        if not password:
            errors.append("كلمة المرور مطلوبة.")
        else:
            try:
                validate_password(password)
            except ValidationError as exc:
                errors.extend(exc.messages)
        if not any(sections.values()):
            errors.append("اختر صلاحية واحدة على الأقل.")

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username, email=email, password=password,
                    first_name=first_name, is_staff=True, is_superuser=False,
                )
                StaffAccess.objects.create(
                    user=user, created_by=request.user, **_as_access_fields(sections)
                )
            messages.success(
                request,
                f"تم إنشاء حساب «{username}». سلّم بيانات الدخول للموظف — "
                "يمكنه تغيير كلمة المرور من صفحة حسابه.",
            )
            return redirect("staff_list")

    return render(request, "site_cars/staff_form.html", {
        "form": form, "sections": _section_rows(sections), "is_add": True,
    })


@site_admin_required
def staff_edit(request, pk):
    _require_tenant_schema()
    member = get_object_or_404(_staff_queryset(), pk=pk)
    access, _ = StaffAccess.objects.get_or_create(user=member)

    email = member.email
    first_name = member.first_name
    is_active = member.is_active
    sections = {key: getattr(access, SECTION_FIELDS[key]) for key in SECTION_KEYS}

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        first_name = (request.POST.get("first_name") or "").strip()
        is_active = bool(request.POST.get("is_active"))
        password = request.POST.get("password") or ""
        sections = _sections_from_post(request)

        errors = []
        if email and User.objects.filter(email__iexact=email).exclude(pk=member.pk).exists():
            errors.append("البريد الإلكتروني مستخدم بالفعل.")
        if password:
            try:
                validate_password(password, member)
            except ValidationError as exc:
                errors.extend(exc.messages)
        if not any(sections.values()):
            errors.append("اختر صلاحية واحدة على الأقل.")

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            with transaction.atomic():
                member.email = email
                member.first_name = first_name
                member.is_active = is_active
                if password:
                    member.set_password(password)
                member.save()
                for field, value in _as_access_fields(sections).items():
                    setattr(access, field, value)
                access.save()
            messages.success(request, f"تم تحديث صلاحيات «{member.username}».")
            return redirect("staff_list")

    return render(request, "site_cars/staff_form.html", {
        "form": {
            "username": member.username,
            "email": email,
            "first_name": first_name,
            "is_active": is_active,
        },
        "sections": _section_rows(sections),
        "member": member,
        "is_add": False,
    })


@site_admin_required
@require_POST
def staff_delete(request, pk):
    _require_tenant_schema()
    member = get_object_or_404(_staff_queryset(), pk=pk)
    username = member.username
    member.delete()
    messages.success(request, f"تم حذف حساب «{username}».")
    return redirect("staff_list")


@site_admin_required
def staff_password_suggestion(request):
    """Feed the 'Generate' button next to the password field."""
    _require_tenant_schema()
    return JsonResponse({"password": _generate_password()})
