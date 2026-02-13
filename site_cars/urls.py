from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard, name='site_dashboard'),
    path('our-cars/', views.site_car_list, name='site_car_list'),
    path('our-cars/<int:pk>/', views.site_car_detail, name='site_car_detail'),
    path('sold-cars/', views.sold_cars, name='sold_cars'),
    path('order/<int:pk>/', views.place_order, name='place_order'),
    path('my-orders/', views.my_orders, name='my_orders'),
    path('my-orders/<int:pk>/', views.order_detail, name='order_detail'),
    path('rate/<int:pk>/', views.rate_car, name='rate_car'),
    path('inbox/', views.inbox, name='inbox'),
    path('inbox/<int:pk>/', views.message_detail, name='message_detail'),
    path('inbox/compose/', views.compose_message, name='compose_message'),
    path('send-email/', views.send_email_view, name='send_email'),
    path('upload-auction/', views.upload_auction_json, name='upload_auction_json'),
]
