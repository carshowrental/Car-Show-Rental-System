import re
from datetime import datetime
from datetime import timedelta

import cv2
import numpy as np
import pytesseract
import requests
from PIL import Image
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db import IntegrityError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.http import require_http_methods

from backend.models import Car, Reservation, UserProfile, PasswordResetToken


def view_home(request):
    all_cars = Car.objects.all().order_by('-year')
    featured_cars = [car for car in all_cars if car.is_currently_available][:3]  # Get the first 3 available cars

    return render(request, 'frontend/home.html', {'featured_cars': featured_cars})


def user_register(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        phone_number = request.POST.get('phone_number')
        address = request.POST.get('address')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')

        # Validate that all fields are filled
        if password1 != password2:
            messages.error(request, 'Passwords do not match.')
        elif len(password1) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
        elif User.objects.filter(username=username).exists():
            messages.error(request, 'This username is already taken. Please use a different username.')
        elif User.objects.filter(email=email).exists():
            messages.error(request, 'This email is already registered. Please use a different email.')
        elif UserProfile.objects.filter(phone_number=phone_number).exists():
            messages.error(request, 'This phone number is already registered. Please use a different phone number.')
        else:
            # Create the user
            user = User.objects.create_user(username=username, email=email, password=password1)

            # Create the user profile with phone number and address
            UserProfile.objects.create(
                user=user,
                phone_number=phone_number,
                address=address
            )

            messages.success(request, f'Account created for {username}. You can now log in.')
            return redirect('login')

    return render(request, 'frontend/register.html')


def user_login(request):
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
    return render(request, 'frontend/login.html')


@login_required
def user_logout(request):
    logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('home')


def forgot_password(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            user = User.objects.get(email=email)
            token = PasswordResetToken.objects.create(
                user=user,
                expires_at=timezone.localtime(timezone.now()) + timedelta(hours=24)
            )

            reset_url = request.build_absolute_uri(
                reverse('reset_password', args=[str(token.token)])
            )

            subject = 'Password Reset for Car Show Rentals'
            html_message = render_to_string('frontend/reset_password_email.html', {
                'user': user,
                'reset_url': reset_url,
            })
            plain_message = strip_tags(html_message)

            send_mail(
                subject,
                plain_message,
                settings.EMAIL_HOST_USER,
                [user.email],
                html_message=html_message,
                fail_silently=False,
            )

            messages.success(request, 'Password reset instructions have been sent to your email.')
            return redirect('login')
        except User.DoesNotExist:
            messages.error(request, 'No user with that email address exists.')

    return render(request, 'frontend/forgot_password.html')


def reset_password(request, token):
    try:
        reset_token = PasswordResetToken.objects.get(token=token)
        if not reset_token.is_valid():
            messages.error(request, 'This password reset link has expired.')
            return redirect('login')

        if request.method == 'POST':
            password1 = request.POST.get('password1')
            password2 = request.POST.get('password2')

            if password1 != password2:
                messages.error(request, 'Passwords do not match.')
            elif len(password1) < 8:
                messages.error(request, 'Password must be at least 8 characters long.')
            else:
                user = reset_token.user
                user.password = make_password(password1)
                user.save()
                reset_token.delete()
                messages.success(request,
                                 'Your password has been reset successfully. You can now log in with your new password.')
                return redirect('login')

        return render(request, 'frontend/reset_password.html', {'token': token})

    except PasswordResetToken.DoesNotExist:
        messages.error(request, 'Invalid password reset link.')
        return redirect('login')


API4AI_URL = "https://api.api4ai.com/ocr/v1/extract"
API4AI_HEADERS = {
    'X-Api-Key': '2c9371458amsh8ce97c8f8b8e6bcp17ec30jsn01addc3e9068'  # Replace with your actual API key
}


def extract_license_info(ocr_result):
    text = ocr_result['text']

    license_number_match = re.search(r'[A-Z]\d{2}-\d{2}-\d{6}', text)
    license_number = license_number_match.group(0) if license_number_match else None

    date_match = re.search(r'(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/(19|20)\d{2}', text)
    expiration_date = date_match.group(0) if date_match else None

    name_match = re.search(r'([A-Z]+\s){2,}[A-Z]+', text)
    name = name_match.group(0) if name_match else None

    address_match = re.search(r'ADDRESS:\s*(.*)', text)
    address = address_match.group(1) if address_match else None

    return license_number, expiration_date, name, address


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
            new_username = request.POST.get('username', '')
            new_email = request.POST.get('email', '')

            # Check if the new username already exists (excluding the current user)
            if User.objects.filter(username=new_username).exclude(id=user.id).exists():
                messages.error(request, 'This username is already taken. Please choose a different one.')
                return redirect('profile')

            # Check if the new email already exists (excluding the current user)
            if User.objects.filter(email=new_email).exclude(id=user.id).exists():
                messages.error(request, 'This email is already in use. Please use a different email address.')
                return redirect('profile')

            user.first_name = request.POST.get('first_name', '')
            user.last_name = request.POST.get('last_name', '')
            user.username = new_username
            user.email = new_email
            user.save()

            user_profile.phone_number = request.POST.get('phone_number', '')
            user_profile.address = request.POST.get('address', '')
            user_profile.save()

            messages.success(request, 'Your profile has been updated successfully.')
            return redirect('profile')
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
                update_session_auth_hash(request, user)
                messages.success(request, 'Your password was successfully updated!')
            return redirect('profile')
        elif action == 'upload_license':
            license_image = request.FILES.get('license_image')
            if license_image:
                try:
                    files = {'image': license_image}
                    response = requests.post(API4AI_URL, headers=API4AI_HEADERS, files=files)
                    response.raise_for_status()

                    ocr_result = response.json()
                    license_number, expiration_date, name, address = extract_license_info(
                        ocr_result['results'][0]['ocr'][0])

                    if license_number and expiration_date:
                        user_profile.license_image = license_image
                        user_profile.license_number = license_number
                        user_profile.license_expiration = expiration_date
                        user_profile.save()

                        if name:
                            name_parts = name.split()
                            if len(name_parts) > 1:
                                user.first_name = name_parts[0]
                                user.last_name = ' '.join(name_parts[1:])
                                user.save()

                        if address:
                            user_profile.address = address
                            user_profile.save()

                        messages.success(request, "Your driver's license has been uploaded and processed successfully.")
                    else:
                        messages.warning(request,
                                         "Could not extract all required information. Please verify and correct the details.")
                except requests.RequestException as e:
                    messages.error(request, f"An error occurred while processing the image: {str(e)}")
                except Exception as e:
                    messages.error(request, f"An unexpected error occurred: {str(e)}")
            else:
                messages.error(request, "Please upload a license image.")
            return redirect('profile')

    return render(request, 'frontend/user_profile.html', {
        'user': user,
        'user_profile': user_profile,
    })


def view_cars(request):
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
        cars = cars.filter(daily_rate__gte=min_price)
    if max_price:
        cars = cars.filter(daily_rate__lte=max_price)

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

    return render(request, 'frontend/cars.html', context)


def car_detail(request, car_id):
    car = get_object_or_404(Car, id=car_id)
    images = car.carimages_set.all()

    # Split the features string into a list, respecting newlines
    features = [feature.strip() for feature in car.features.split('\n') if feature.strip()]

    context = {
        'car': car,
        'images': images,
        'features': features,  # Pass the processed features to the template
    }
    return render(request, 'frontend/car_detail.html', context)


@require_http_methods(["POST"])
def check_car_availability(request):
    try:
        car_id = request.POST.get('car_id')
        rate_type = request.POST.get('rate_type', 'daily')

        car = get_object_or_404(Car, id=car_id)
        now = timezone.localtime(timezone.now())

        if rate_type == 'hourly':
            # For hourly rentals, we need both date and time
            start_str = request.POST.get('start_datetime')
            start_datetime = timezone.make_aware(datetime.strptime(start_str, '%Y-%m-%dT%H:%M'))
            duration_hours = int(request.POST.get('duration', 1))
            end_datetime = start_datetime + timedelta(hours=duration_hours)
        else:
            # For daily and weekly rentals, we work with dates
            start_str = request.POST.get('start_date')
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            duration = int(request.POST.get('duration', 1))

            if rate_type == 'weekly':
                end_date = start_date + timedelta(weeks=duration)
            else:  # daily
                end_date = start_date + timedelta(days=duration)

            # Convert to datetime for consistent handling
            start_datetime = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
            end_datetime = timezone.make_aware(datetime.combine(end_date, datetime.min.time()))

        # Validate dates/times
        if start_datetime >= end_datetime:
            return JsonResponse({
                'available': False,
                'message': 'End time must be after start time'
            })

        if start_datetime < now:
            return JsonResponse({
                'available': False,
                'message': 'Cannot book in the past'
            })

        # Check availability and get total units
        get_available_total_units = car.get_available_total_units(start_datetime, end_datetime)

        return JsonResponse({
            'available': get_available_total_units > 0,
            'get_available_total_units': get_available_total_units,
            'message': f'{get_available_total_units} units available' if get_available_total_units > 0 else 'No units available for these dates/times'
        })

    except Exception as e:
        return JsonResponse({
            'available': False,
            'message': str(e)
        }, status=400)



@login_required
def view_reservations(request):
    now = timezone.localtime(timezone.now())
    reservations = Reservation.objects.filter(user=request.user).order_by('-start_date')

    # Classify reservations
    for reservation in reservations:
        # Convert datetime to date for comparison if rate_type is not hourly
        if reservation.rate_type == 'hourly':
            start = reservation.start_date
            end = reservation.end_date
            current = now
        else:
            start = reservation.start_date.date()
            end = reservation.end_date.date()
            current = now.date()

        if reservation.status == 'paid' and start <= current <= end:
            reservation.status = 'active'
        elif reservation.status == 'paid' and end < current:
            reservation.status = 'completed'
        reservation.save()

    return render(request, 'frontend/reservations.html', {'reservations': reservations})


@login_required
def create_reservation(request, car_id):
    if request.method == 'POST':
        car = get_object_or_404(Car, id=car_id)
        rate_type = request.POST.get('rate_type')
        duration = int(request.POST.get('duration', 1))
        total_price = float(request.POST.get('total_price', 0))

        try:
            user_profile = request.user.userprofile
            if not user_profile.license_image:
                messages.error(request, "Please upload your driver's license before making a reservation.")
                return redirect('profile')
        except UserProfile.DoesNotExist:
            messages.error(request,
                           "Please complete your profile and upload your driver's license before making a reservation.")
            return redirect('profile')

        try:
            # Handle different date formats based on rate type
            if rate_type == 'hourly':
                start_str = request.POST.get('start_datetime')
                start_datetime = timezone.make_aware(datetime.strptime(start_str, '%Y-%m-%dT%H:%M'))
                end_datetime = start_datetime + timedelta(hours=duration)
            else:
                start_str = request.POST.get('start_date')
                start_date = datetime.strptime(start_str, '%Y-%m-%d').date()

                if rate_type == 'weekly':
                    end_date = start_date + timedelta(weeks=duration)
                else:  # daily
                    end_date = start_date + timedelta(days=duration)

                # Convert to datetime for consistent handling
                start_datetime = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
                end_datetime = timezone.make_aware(datetime.combine(end_date, datetime.min.time()))

            # Get the available total units for the period
            get_available_total_units = car.get_available_total_units(start_datetime, end_datetime)

            if get_available_total_units > 0:
                reservation = Reservation.objects.create(
                    user=request.user,
                    car=car,
                    start_date=start_datetime,
                    end_date=end_datetime,
                    rate_type=rate_type,
                    total_price=total_price,
                    status='pending'
                )
                return redirect('payment', reservation_id=reservation.id)
            else:
                messages.error(request, 'No units available for the selected dates/times.')
                return redirect('car_detail', car_id=car.id)

        except ValueError as e:
            messages.error(request, f'Invalid date/time format: {str(e)}')
            return redirect('car_detail', car_id=car.id)
        except Exception as e:
            messages.error(request, f'An error occurred: {str(e)}')
            return redirect('car_detail', car_id=car.id)

    return redirect('cars')


@login_required
def cancel_reservation(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id, user=request.user)

    reservation.status = 'cancelled'
    reservation.save()
    messages.success(request, 'Reservation cancelled successfully.')

    return redirect('reservations')


@login_required
def delete_reservation(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)
    reservation.delete()

    messages.success(request, f'The reservation for { reservation.car.brand } { reservation.car.model } has been successfully deleted.')
    return redirect('reservations')


@login_required
def view_payment(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id, user=request.user)
    return render(request, 'frontend/payment.html', {'reservation': reservation})


@login_required
@require_http_methods(["POST"])
def process_payment(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id, user=request.user)

    if 'receipt' not in request.FILES:
        return JsonResponse({'success': False, 'error': 'No receipt uploaded'})

    receipt_image = request.FILES['receipt']

    # Convert the uploaded file to an image that OpenCV can process
    image = Image.open(receipt_image)
    image = np.array(image.convert('RGB'))
    image = image[:, :, ::-1].copy()

    # Preprocess the image
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]

    # Perform OCR
    text = pytesseract.image_to_string(thresh)

    # Extract reference number and amount
    ref_number_match = re.search(r'Reference Number:\s*(\w+)', text)
    amount_match = re.search(r'Amount:\s*₱?([\d,]+\.?\d*)', text)

    if not ref_number_match or not amount_match:
        return JsonResponse({'success': False, 'error': 'Could not extract reference number or amount from receipt'})

    ref_number = ref_number_match.group(1)
    amount = float(amount_match.group(1).replace(',', ''))

    # Verify the amount
    if amount != float(reservation.total_price):
        return JsonResponse({'success': False, 'error': 'Payment amount does not match the reservation total'})

    # Update reservation status
    reservation.status = 'paid'
    reservation.payment_id = ref_number
    reservation.save()

    return JsonResponse({'success': True, 'reference_number': ref_number})


@login_required
def payment_confirmation(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id, user=request.user)
    return render(request, 'frontend/payment_confirmation.html', {'reservation': reservation})


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

    return render(request, 'frontend/contact_us.html')


def rental_policy(request):
    return render(request, 'frontend/rental_policy.html')
