from django.urls import path

from . import views

urlpatterns = [
    path("dashboard/assistant/ask/", views.assistant_ask, name="assistant_ask"),
]
