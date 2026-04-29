from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.billing_dashboard, name="dashboard"),
    path("checkout/", views.create_checkout_session, name="checkout"),
    path("success/", views.checkout_success, name="success"),
    path("payment-link/<int:tenant_id>/", views.create_payment_link, name="payment_link"),
    path("payment-link-generic/", views.create_generic_payment_link, name="payment_link_generic"),
]
