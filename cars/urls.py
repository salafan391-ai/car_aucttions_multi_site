from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('cars/', views.car_list, name='car_list'),
    path('cars/<int:pk>/', views.car_detail, name='car_detail'),
    path('expired-auctions/', views.expired_auctions, name='expired_auctions'),
    path('api/models/', views.api_models_by_manufacturer, name='api_models_by_manufacturer'),
    path('api/badges/', views.api_badges_by_model, name='api_badges_by_model'),
    path('car-request/', views.car_request, name='car_request'),
    path('contact/', views.contact, name='contact'),
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='registration/password_reset.html',
        email_template_name='registration/password_reset_email.html',
        subject_template_name='registration/password_reset_subject.txt',
        success_url='/password-reset/done/',
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='registration/password_reset_done.html',
    ), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='registration/password_reset_confirm.html',
        success_url='/password-reset-complete/',
    ), name='password_reset_confirm'),
    path('password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html',
    ), name='password_reset_complete'),
    path('wishlist/', views.wishlist, name='wishlist'),
    path('wishlist/toggle/<int:car_id>/', views.toggle_wishlist, name='toggle_wishlist'),
    path('wishlist/count/', views.wishlist_count, name='wishlist_count'),
    
    # Posts URLs
    path('posts/', views.post_list, name='post_list'),
    path('posts/<int:pk>/', views.post_detail, name='post_detail'),
    path('posts/<int:pk>/like/', views.post_like_toggle, name='post_like_toggle'),
    path('posts/<int:pk>/comment/', views.post_comment_add, name='post_comment_add'),
    path('posts/comment/<int:pk>/delete/', views.post_comment_delete, name='post_comment_delete'),
]
