from django.urls import path

from . import views

urlpatterns = [
    # Public catalogue
    path("parts/", views.parts_list, name="parts_list"),
    path("parts/<int:pk>/", views.parts_detail, name="parts_detail"),
    path("accessories/", views.accessories_list, name="accessories_list"),
    path("accessories/<int:pk>/", views.accessories_detail, name="accessories_detail"),
    path("shop/request/", views.shop_request, name="shop_request"),

    # Staff CRUD (parts + accessories share these, distinguished by ?kind=)
    path("dashboard/shop/", views.shop_manage, name="shop_manage"),
    path("dashboard/shop/requests/", views.shop_requests, name="shop_requests"),
    path("dashboard/shop/requests/<int:pk>/toggle/", views.shop_request_toggle, name="shop_request_toggle"),
    path("dashboard/shop/import/", views.shop_import, name="shop_import"),
    path("dashboard/shop/add/", views.shop_add, name="shop_add"),
    path("dashboard/shop/<int:pk>/edit/", views.shop_edit, name="shop_edit"),
    path("dashboard/shop/<int:pk>/delete/", views.shop_delete, name="shop_delete"),
    path("dashboard/shop/<int:pk>/delete-image/<int:image_id>/", views.shop_delete_image, name="shop_delete_image"),
    path("dashboard/shop/<int:pk>/toggle-stock/", views.shop_toggle_stock, name="shop_toggle_stock"),
]
