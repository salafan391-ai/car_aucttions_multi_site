from django.apps import AppConfig


class SiteCarsConfig(AppConfig):
    name = "site_cars"

    def ready(self):
        import site_cars.signals  # noqa: F401
