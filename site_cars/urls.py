from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard, name='site_dashboard'),
    path('our-cars/', views.site_car_list, name='site_car_list'),
    path('our-cars/add/', views.site_car_add, name='site_car_add'),
    path('our-cars/<int:pk>/', views.site_car_detail, name='site_car_detail'),
    path('our-cars/<int:pk>/edit/', views.site_car_edit, name='site_car_edit'),
    path('our-cars/<int:pk>/delete/', views.site_car_delete, name='site_car_delete'),
    path('our-cars/<int:pk>/status/', views.site_car_change_status, name='site_car_change_status'),
    path('our-cars/<int:pk>/delete-image/<int:image_id>/', views.site_car_delete_image, name='site_car_delete_image'),
    path('sold-cars/', views.sold_cars, name='sold_cars'),
    path('order/<int:pk>/', views.place_order, name='place_order'),
    path('my-orders/', views.my_orders, name='my_orders'),
    path('my-orders/<int:pk>/', views.order_detail, name='order_detail'),
    path('rate/<int:pk>/', views.rate_car, name='rate_car'),
    path('rating/<int:pk>/approve/', views.approve_rating, name='approve_rating'),
    path('rating/<int:pk>/reject/', views.reject_rating, name='reject_rating'),
    path('inbox/', views.inbox, name='inbox'),
    path('inbox/<int:pk>/', views.message_detail, name='message_detail'),
    path('inbox/compose/', views.compose_message, name='compose_message'),
    path('send-email/', views.send_email_view, name='send_email'),
    path('upload-auction/', views.upload_auction_json, name='upload_auction_json'),
]
