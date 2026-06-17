from django.urls import path

from . import views

app_name = "site_builder"

urlpatterns = [
    # Dashboard page-builder editor (staff)
    path("dashboard/pages/", views.pages_list, name="pages_list"),
    path("dashboard/pages/new/", views.page_create, name="page_create"),
    path("dashboard/pages/<int:pk>/", views.page_edit, name="page_edit"),
    path("dashboard/pages/<int:pk>/settings/", views.page_settings, name="page_settings"),
    path("dashboard/pages/<int:pk>/delete/", views.page_delete, name="page_delete"),
    path("dashboard/pages/<int:pk>/sections/new/", views.section_edit, name="section_create"),
    path("dashboard/pages/<int:pk>/sections/<int:sec_pk>/", views.section_edit, name="section_edit"),
    path("dashboard/pages/<int:pk>/sections/<int:sec_pk>/delete/", views.section_delete, name="section_delete"),
    path("dashboard/pages/<int:pk>/sections/<int:sec_pk>/move/<str:direction>/", views.section_move, name="section_move"),
    # Public page
    path("p/<slug:slug>/", views.page_view, name="page"),
]
