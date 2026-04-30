from pathlib import Path

from django.conf import settings
from django.db import connection
from django.template.loaders.filesystem import Loader as FilesystemLoader


class TenantThemeLoader(FilesystemLoader):
    """Resolves templates from the current tenant's theme directory first.

    A tenant whose `template_theme` is `luxury` will have any template
    that exists at `templates/themes/luxury/<name>` win over the same
    name in `templates/<name>`. Templates not present in the theme tree
    fall through to the next loader (filesystem → app dirs).
    """

    def get_dirs(self):
        tenant = getattr(connection, "tenant", None)
        theme = getattr(tenant, "template_theme", None) or "default"
        if theme == "default":
            return []
        theme_dir = Path(settings.BASE_DIR) / "templates" / "themes" / theme
        return [str(theme_dir)] if theme_dir.is_dir() else []
