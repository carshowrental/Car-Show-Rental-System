import base64
import logging
import os

from dateutil import parser
import easyocr
import cv2
import numpy as np
from django.conf import settings
import logging
import requests
from django.conf import settings
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from backend.models import Car, Reservation, UserProfile
from datetime import datetime
import stripe
from django.db.models import Q
from django.utils import timezone
from django.contrib.auth.hashers import check_password
from django.contrib.auth import update_session_auth_hash
import cv2
import numpy as np
import pytesseract
from PIL import Image
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.conf import settings
import re
from datetime import datetime
from io import BytesIO

from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

def home(request):
    today = timezone.now().date()
    all_cars = Car.objects.all().order_by('-year')
    featured_cars = [car for car in all_cars if car.is_currently_available][:3]  # Get the first 3 available cars
    return render(request, 'homepage.html', {'featured_cars': featured_cars})


@login_required
def reservation_history(request):
    now = timezone.now()
    upcoming_reservations = Reservation.objects.filter(user=request.user, start_date__gt=now).order_by('start_date')
    current_reservations = Reservation.objects.filter(user=request.user, start_date__lte=now,
                                                      end_date__gte=now).order_by('start_date')
    past_reservations = Reservation.objects.filter(user=request.user, end_date__lt=now).order_by('-end_date')

    context = {
        'upcoming_reservations': upcoming_reservations,
        'current_reservations': current_reservations,
        'past_reservations': past_reservations,
    }
    return render(request, 'reservation_history.html', context)


def contact_us(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        message = request.POST.get('message')

        if name and email and message:
            # Process the form data (e.g., send email, save to database)
            # You can add your logic here to handle the contact form submission
            messages.success(request, 'Your message has been sent. We will get back to you soon!')
            return redirect('contact_us')
        else:
            messages.error(request, 'Please fill in all fields.')

    return render(request, 'contact_us.html')


def car_list(request):
    cars = Car.objects.all()

    # Search functionality
    search_query = request.GET.get('search')
    if search_query:
        cars = cars.filter(
            Q(brand__icontains=search_query) |
            Q(model__icontains=search_query)
        )

    # Filter by car type
    car_type = request.GET.get('car_type')
    if car_type:
        cars = cars.filter(car_type=car_type)

    # Filter by price range
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    if min_price:
        cars = cars.filter(price_per_day__gte=min_price)
    if max_price:
        cars = cars.filter(price_per_day__lte=max_price)

    # Filter by year range
    min_year = request.GET.get('min_year')
    max_year = request.GET.get('max_year')
    if min_year:
        cars = cars.filter(year__gte=min_year)
    if max_year:
        cars = cars.filter(year__lte=max_year)

    # Get unique car types for the filter dropdown
    car_types = Car.CAR_TYPES

    # Pagination
    paginator = Paginator(cars, 9)  # Show 9 cars per page
    page = request.GET.get('page')
    try:
        cars = paginator.page(page)
    except PageNotAnInteger:
        cars = paginator.page(1)
    except EmptyPage:
        cars = paginator.page(paginator.num_pages)

    context = {
        'cars': cars,
        'car_types': car_types,
        'search_query': search_query,
        'selected_car_type': car_type,
        'min_price': min_price,
        'max_price': max_price,
        'min_year': min_year,
        'max_year': max_year,
    }

    return render(request, 'car_list.html', context)


def car_detail(request, car_id):
    car = get_object_or_404(Car, id=car_id)
    images = car.carimages_set.all()

    # Split the features string into a list
    features = [feature.strip() for feature in car.features.split(',') if feature.strip()]

    context = {
        'car': car,
        'images': images,
        'features': features,  # Pass the processed features to the template
    }
    return render(request, 'car_detail.html', context)


@login_required
def create_reservation(request, car_id):
    if request.method == 'POST':
        # Check if user has uploaded a license
        try:
            if not request.user.userprofile.license_image:
                messages.error(request, "Please upload your driver's license before making a reservation.")
                return redirect('license_upload')
        except UserProfile.DoesNotExist:
            messages.error(request, "Please upload your driver's license before making a reservation.")
            return redirect('license_upload')

        car = get_object_or_404(Car, id=car_id)
        start_date = datetime.strptime(request.POST['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(request.POST['end_date'], '%Y-%m-%d').date()

        if car.is_available(start_date, end_date):
            # Calculate total price
            days = (end_date - start_date).days + 1
            total_price = car.price_per_day * days

            # Create reservation
            reservation = Reservation.objects.create(
                user=request.user,
                car=car,
                start_date=start_date,
                end_date=end_date,
                total_price=total_price,
                status='pending'
            )

            return redirect('payment', reservation_id=reservation.id)
        else:
            messages.error(request, 'Car is not available for the selected dates.')
            return redirect('car_detail', car_id=car.id)

    return redirect('car_list')


def check_availability(request):
    car_id = request.GET.get('car_id')
    start_date = datetime.strptime(request.GET.get('start_date'), '%Y-%m-%d').date()
    end_date = datetime.strptime(request.GET.get('end_date'), '%Y-%m-%d').date()

    car = get_object_or_404(Car, id=car_id)
    is_available = car.is_available(start_date, end_date)

    return JsonResponse({'available': is_available})


@require_http_methods(["GET", "POST"])
def payment(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)

    if request.method == 'GET':
        # Check if this is a return from GCash
        status = request.GET.get('status')
        if status:
            return handle_gcash_return(request, reservation)

        # If not a return from GCash, just display the payment page
        return render(request, 'payment.html', {'reservation': reservation})

    # Handle POST request (initiating payment)
    try:
        source = create_gcash_source(request, reservation)
        # Save the source ID to your reservation
        reservation.payment_source_id = source['id']
        reservation.save()
        # Redirect the user to the GCash payment page
        return redirect(source['attributes']['redirect']['checkout_url'])
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect('payment', reservation_id=reservation_id)


def handle_gcash_return(request, reservation):
    status = request.GET.get('status')
    if status == 'success':
        # Verify the payment status with PayMongo
        source = verify_payment_source(reservation)
        if source and source['attributes']['status'] == 'chargeable':
            # Create the actual payment
            payment = create_payment(reservation, source)
            if payment and payment['attributes']['status'] == 'paid':
                reservation.status = 'paid'
                reservation.save()
                messages.success(request, "Payment successful! Your reservation is confirmed.")
            else:
                messages.error(request, "Payment creation failed. Please contact support.")
        else:
            messages.error(request, "Payment verification failed. Please try again or contact support.")
    elif status == 'failed':
        messages.error(request, "Payment failed. Please try again or choose a different payment method.")

    return redirect('reservation_detail', reservation_id=reservation.id)


def create_gcash_source(request, reservation):
    headers = get_paymongo_headers()
    payload = {
        'data': {
            'attributes': {
                'type': 'gcash',
                'amount': int(reservation.total_price * 100),  # Amount in cents
                'currency': 'PHP',
                'redirect': {
                    'success': request.build_absolute_uri(
                        reverse('payment', args=[reservation.id])) + '?status=success',
                    'failed': request.build_absolute_uri(reverse('payment', args=[reservation.id])) + '?status=failed'
                }
            }
        }
    }
    response = requests.post(f'{settings.PAYMONGO_API_URL}/sources', json=payload, headers=headers)
    response.raise_for_status()
    return response.json()['data']


def verify_payment_source(reservation):
    headers = get_paymongo_headers()
    response = requests.get(f'{settings.PAYMONGO_API_URL}/sources/{reservation.payment_source_id}', headers=headers)
    if response.status_code == 200:
        return response.json()['data']
    return None


def create_payment(reservation, source):
    headers = get_paymongo_headers()
    payload = {
        'data': {
            'attributes': {
                'amount': int(reservation.total_price * 100),
                'currency': 'PHP',
                'source': {
                    'id': source['id'],
                    'type': 'source'
                }
            }
        }
    }
    response = requests.post(f'{settings.PAYMONGO_API_URL}/payments', json=payload, headers=headers)
    if response.status_code == 200:
        return response.json()['data']
    return None





def get_paymongo_headers():

    secret_key = settings.PAYMONGO_SECRET_KEY
    encoded_key = base64.b64encode(secret_key.encode()).decode()
    return {
        'Authorization': f'Basic {encoded_key}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }


@login_required
def user_dashboard(request):
    now = timezone.now()
    reservations = Reservation.objects.filter(user=request.user).order_by('-start_date')

    # Classify reservations
    for reservation in reservations:
        if reservation.status == 'paid' and reservation.start_date <= now.date() <= reservation.end_date:
            reservation.status = 'active'
        elif reservation.status == 'paid' and reservation.end_date < now.date():
            reservation.status = 'completed'
        reservation.save()

    # Check for newly cancelled reservations
    newly_cancelled = reservations.filter(status='cancelled', cancellation_notified=False)
    for reservation in newly_cancelled:
        messages.warning(request,
                         f'Your reservation for {reservation.car.brand} {reservation.car.model} from {reservation.start_date} to {reservation.end_date} has been cancelled due to overlapping with a confirmed booking.')
        reservation.cancellation_notified = True
        reservation.save()

    return render(request, 'user_dashboard.html', {'reservations': reservations})


@login_required
def cancel_reservation(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id, user=request.user)

    if reservation.status == 'active':
        reservation.status = 'cancelled'
        reservation.save()
        messages.success(request, 'Reservation cancelled successfully.')
    else:
        messages.error(request, 'This reservation cannot be cancelled.')

    return redirect('user_dashboard')


def register(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')

        if not (username and email and password1 and password2):
            messages.error(request, 'Please fill in all fields.')
        elif password1 != password2:
            messages.error(request, 'Passwords do not match.')
        elif len(password1) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
        else:
            try:
                user = User.objects.create_user(username, email, password1)
                messages.success(request, f'Account created for {username}. You can now log in.')
                return redirect('login')
            except IntegrityError:
                messages.error(request, 'That username is already taken. Please choose a different one.')

    return render(request, 'registration.html')


def login_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, 'You have been logged in.')
            return redirect('home')
        else:
            messages.error(request, 'Invalid username or password.')
    return render(request, 'login.html')


@login_required
def logout_view(request):
    logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('home')


# API4AI endpoint and headers
API4AI_URL = "https://api.api4ai.com/ocr/v1/extract"
API4AI_HEADERS = {
    'X-Api-Key': '2c9371458amsh8ce97c8f8b8e6bcp17ec30jsn01addc3e9068'  # Replace with your actual API key
}


def extract_license_info(ocr_result):
    text = ocr_result['text']

    # Extract license number (format: X##-##-######)
    license_number_match = re.search(r'[A-Z]\d{2}-\d{2}-\d{6}', text)
    license_number = license_number_match.group(0) if license_number_match else None

    # Extract expiration date (format: MM/DD/YYYY)
    date_match = re.search(r'(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/(19|20)\d{2}', text)
    expiration_date = date_match.group(0) if date_match else None

    # Extract name (typically in all caps)
    name_match = re.search(r'([A-Z]+\s){2,}[A-Z]+', text)
    name = name_match.group(0) if name_match else None

    # Extract address (typically follows "ADDRESS:")
    address_match = re.search(r'ADDRESS:\s*(.*)', text)
    address = address_match.group(1) if address_match else None

    return license_number, expiration_date, name, address


@login_required
def license_upload(request):
    try:
        user_profile = request.user.userprofile
    except UserProfile.DoesNotExist:
        user_profile = UserProfile(user=request.user)

    if request.method == 'POST':
        license_image = request.FILES.get('license_image')

        if license_image:
            try:
                # Send image to API4AI
                files = {'image': license_image}
                response = requests.post(API4AI_URL, headers=API4AI_HEADERS, files=files)
                response.raise_for_status()  # Raise an exception for bad status codes

                ocr_result = response.json()

                # Extract license information from OCR result
                license_number, expiration_date, name, address = extract_license_info(
                    ocr_result['results'][0]['ocr'][0])

                if license_number and expiration_date:
                    user_profile.license_image = license_image
                    user_profile.license_number = license_number
                    user_profile.license_expiration = expiration_date
                    user_profile.save()
                    messages.success(request, "Your driver's license has been uploaded and processed successfully.")
                else:
                    messages.warning(request,
                                     "Could not extract all required information. Please verify and correct the details.")

                context = {
                    'user_profile': user_profile,
                    'extracted_license_number': license_number,
                    'extracted_expiration_date': expiration_date,
                    'extracted_name': name,
                    'extracted_address': address,
                }
                return render(request, 'license_upload.html', context)

            except requests.RequestException as e:
                messages.error(request, f"An error occurred while processing the image: {str(e)}")
            except Exception as e:
                messages.error(request, f"An unexpected error occurred: {str(e)}")
        else:
            messages.error(request, "Please upload a license image.")

    return render(request, 'license_upload.html', {'user_profile': user_profile})


@login_required
def user_profile(request):
    user = request.user
    try:
        user_profile = user.userprofile
    except UserProfile.DoesNotExist:
        user_profile = UserProfile(user=user)
        user_profile.save()

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_profile':
            user.first_name = request.POST.get('first_name', '')
            user.last_name = request.POST.get('last_name', '')
            user.email = request.POST.get('email', '')
            user.save()

            user_profile.phone_number = request.POST.get('phone_number', '')
            user_profile.address = request.POST.get('address', '')
            user_profile.save()

            messages.success(request, 'Your profile has been updated successfully.')
            return redirect('user_profile')
        elif action == 'change_password':
            old_password = request.POST.get('old_password')
            new_password1 = request.POST.get('new_password1')
            new_password2 = request.POST.get('new_password2')

            if not check_password(old_password, user.password):
                messages.error(request, 'Your old password was entered incorrectly. Please enter it again.')
            elif new_password1 != new_password2:
                messages.error(request, "The two password fields didn't match.")
            elif len(new_password1) < 8:
                messages.error(request, 'Your new password must contain at least 8 characters.')
            else:
                user.set_password(new_password1)
                user.save()
                update_session_auth_hash(request, user)  # Important to keep the user logged in
                messages.success(request, 'Your password was successfully updated!')
            return redirect('user_profile')

    return render(request, 'user_profile.html', {
        'user': user,
        'user_profile': user_profile,
    })


def rental_policy(request):
    return render(request, 'rental_policy.html')
