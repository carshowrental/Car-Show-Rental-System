from django.urls import path
from frontend import views

urlpatterns = [
    path('', views.home, name='home'),
    path('cars/', views.car_list, name='car_list'),
    path('car/<int:car_id>/', views.car_detail, name='car_detail'),
    path('create-reservation/<int:car_id>/', views.create_reservation, name='create_reservation'),
    path('payment/<int:reservation_id>/', views.payment, name='payment'),
    path('check-availability/', views.check_availability, name='check_availability'),
    path('user-dashboard/', views.user_dashboard, name='user_dashboard'),
    path('cancel-reservation/<int:reservation_id>/', views.cancel_reservation, name='cancel_reservation'),
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('license-upload/', views.license_upload, name='license_upload'),
    path('profile/', views.user_profile, name='user_profile'),

    path('reservation-history/', views.reservation_history, name='reservation_history'),
    path('contact-us/', views.contact_us, name='contact_us'),

    path('rental-policy/', views.rental_policy, name='rental_policy'),
]