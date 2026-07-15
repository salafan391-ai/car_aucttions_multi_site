from .permissions import allowed_sections, is_site_admin


def staff_permissions(request):
    """Expose the current account's dashboard access to every template.

    ``perms`` is already taken by ``django.contrib.auth``, so these are namespaced:

        {% if can.cars %} ... {% endif %}
        {% if is_site_admin %} ... {% endif %}
    """
    user = getattr(request, "user", None)
    granted = allowed_sections(user)
    return {
        "is_site_admin": is_site_admin(user),
        "can": {key: True for key in granted},
    }
