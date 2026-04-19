from django.apps import AppConfig


class TenantsConfig(AppConfig):
    name = "tenants"

    def ready(self):
        from . import signals  # noqa: F401
