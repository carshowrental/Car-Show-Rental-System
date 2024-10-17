from django.urls import path
from backend import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.admin_login, name='admin_login'),
    path('logout/', views.admin_logout, name='logout'),
    path('cars/', views.car_list, name='admin_car_list'),
    path('cars/add/', views.add_car, name='add_car'),
    path('cars/<int:car_id>/', views.car_detail, name='admin_car_detail'),
    path('cars/<int:car_id>/edit/', views.edit_car, name='edit_car'),
    path('cars/<int:car_id>/delete/', views.delete_car, name='delete_car'),
    path('users/', views.user_accounts, name='user_accounts'),
    path('users/add/', views.add_user, name='add_user'),
    path('users/<int:user_id>/edit/', views.edit_user, name='edit_user'),
    path('users/<int:user_id>/delete/', views.delete_user, name='delete_user'),
    path('reservations/', views.reservations, name='admin_reservations'),
    path('reservations/add/', views.add_reservation, name='admin_add_reservation'),
    path('reservations/<int:reservation_id>/edit/', views.edit_reservation, name='admin_edit_reservation'),
    path('reservations/<int:reservation_id>/cancel/', views.cancel_reservation, name='admin_cancel_reservation'),
    path('payments/', views.payment_history, name='admin_payment_history'),
    path('profile/', views.profile, name='admin_profile'),
]