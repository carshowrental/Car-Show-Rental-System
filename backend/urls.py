from django.urls import path
from backend import views

urlpatterns = [
    # Admin Dashboard
    path('', views.view_dashboard, name='admin_dashboard'),

    # Admin Authentication
    path('login/', views.admin_login, name='admin_login'),
    path('logout/', views.admin_logout, name='admin_logout'),

    # Password Management
    path('forgot-password/', views.forgot_password, name='admin_forgot_password'),
    path('reset-password/<uuid:token>/', views.reset_password, name='admin_reset_password'),

    # Car Management
    path('cars/', views.view_cars, name='admin_cars'),
    path('cars/<int:car_id>/', views.car_detail, name='admin_car_detail'),
    path('cars/add/', views.add_car, name='admin_add_car'),
    path('cars/<int:car_id>/edit/', views.edit_car, name='admin_edit_car'),
    path('cars/<int:car_id>/delete/', views.delete_car, name='admin_delete_car'),

    # User Management
    path('users/', views.view_user_accounts, name='admin_user_accounts'),
    path('users/add/', views.add_user, name='admin_add_user'),
    path('users/<int:user_id>/edit/', views.edit_user, name='admin_edit_user'),
    path('users/<int:user_id>/delete/', views.delete_user, name='admin_delete_user'),

    # Reservation Management
    path('reservations/', views.view_reservations, name='admin_reservations'),
    path('reservations/add/', views.add_reservation, name='admin_add_reservation'),
    path('reservations/<int:reservation_id>/edit/', views.edit_reservation, name='admin_edit_reservation'),
    path('reservations/<int:reservation_id>/delete/', views.delete_reservation, name='admin_delete_reservation'),

    # Payment Management
    path('payments/', views.view_payments, name='admin_payments'),

    # Admin Profile
    path('profile/', views.view_profile, name='admin_profile'),
]