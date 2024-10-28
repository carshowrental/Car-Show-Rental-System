import re
from datetime import datetime
from datetime import timedelta
import io
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


def compress_image(image_file, max_size_mb=1):
    """
    Compress image to ensure it's under the specified size in MB
    Returns the compressed image as bytes
    """
    # Convert MB to bytes
    max_size_bytes = max_size_mb * 1024 * 1024

    # Open the image from InMemoryUploadedFile
    img = Image.open(image_file)

    # Convert to RGB if PNG (removes alpha channel)
    if img.format == 'PNG':
        img = img.convert('RGB')

    # Initial quality
    quality = 95
    output = io.BytesIO()

    # Try compressing with different quality values until size is under max_size_bytes
    while quality > 5:
        output.seek(0)
        output.truncate(0)
        img.save(output, format='JPEG', quality=quality)
        if output.tell() <= max_size_bytes:
            break
        quality -= 5

    return output.getvalue()


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
            try:
                # Get the license number and expiration date
                license_number = request.POST.get('license_number')
                license_expiration = request.POST.get('license_expiration')

                # Update license image if a new one is provided
                if 'license_image' in request.FILES:
                    license_image = request.FILES['license_image']
                    user_profile.license_image = license_image

                # Update license details
                user_profile.license_number = license_number
                user_profile.license_expiration = license_expiration
                user_profile.save()

                messages.success(request, "Driver's license information updated successfully.")
            except Exception as e:
                messages.error(request, f"An error occurred while saving license information: {str(e)}")

            return redirect('profile')
    return render(request, 'frontend/user_profile.html', {
        'user': user,
        'user_profile': user_profile,
    })


def extract_license_info(image_file):
    """
    Extract License Number and Expiration Date from Philippine Driver's License using OCR.Space API
    """
    url = "https://api.ocr.space/parse/image"
    api_key = settings.OCR_SPACE_API_KEY  # Add this to your Django settings

    try:
        # Compress and convert image to JPEG
        compressed_image = compress_image(image_file)

        files = {
            'file': ('license.jpg', compressed_image, 'image/jpeg')
        }

        payload = {
            'apikey': api_key,
            'language': 'eng',
            'isOverlayRequired': False,
            'detectOrientation': True,
            'scale': True,
            'OCREngine': 2,  # Using OCR Engine 2 for better results
            'filetype': 'jpg'  # Explicitly specify file type
        }

        try:
            response = requests.post(url, files=files, data=payload)
            response.raise_for_status()  # Raise an exception for bad status codes

            result = response.json()

            if result.get('ParsedResults'):
                text = result['ParsedResults'][0]['ParsedText']

                if not text.strip():  # Check if extracted text is empty
                    return None

                lines = text.split('\n')

                # Initialize variables
                license_number = None
                expiration_date = None

                # Method 1: Find by license number pattern and check next date
                license_pattern = r'[A-Z]\d{2}-\d{2}-\d{6}'
                date_pattern = r'\d{4}/\d{2}/\d{2}'

                for i, line in enumerate(lines):
                    # Look for license number
                    license_match = re.search(license_pattern, line)
                    if license_match:
                        license_number = license_match.group(0)
                        # Check the same line and next few lines for a date
                        for j in range(i, min(i + 3, len(lines))):
                            date_match = re.search(date_pattern, lines[j])
                            if date_match:
                                expiration_date = date_match.group(0)
                                break

                # Method 2: If first method fails, find date below "Expiration Date" text
                if not expiration_date:
                    for i, line in enumerate(lines):
                        if 'expiration date' in line.lower():
                            # Check next lines for a date
                            for j in range(i + 1, min(i + 3, len(lines))):
                                date_match = re.search(date_pattern, lines[j])
                                if date_match:
                                    expiration_date = date_match.group(0)
                                    break

                # Method 3: If both methods fail, search for date after license number in the whole text
                if not expiration_date:
                    full_text = ' '.join(lines)
                    license_pos = full_text.find(license_number) if license_number else -1
                    if license_pos != -1:
                        # Search for date pattern after license number
                        remaining_text = full_text[license_pos:]
                        date_match = re.search(date_pattern, remaining_text)
                        if date_match:
                            expiration_date = date_match.group(0)

                # Only return data if at least one field was found
                if license_number or expiration_date:
                    return {
                        'license_number': license_number,
                        'expiration_date': expiration_date
                    }

            return None

        except requests.RequestException as e:
            print(f"Request error: {str(e)}")
            return None

    except Exception as e:
        print(f"Processing error: {str(e)}")
        return None


@login_required
def process_license(request):
    if not request.FILES.get('license_image'):
        return JsonResponse({
            'success': False,
            'error': 'No image provided'
        })

    try:
        license_image = request.FILES['license_image']

        # Check file type
        allowed_types = ['image/jpeg', 'image/png', 'image/jpg']
        if license_image.content_type not in allowed_types:
            return JsonResponse({
                'success': False,
                'error': 'Please upload a JPG or PNG image'
            })

        # Process the image
        result = extract_license_info(license_image)

        if result and (result['license_number'] or result['expiration_date']):
            response_data = {
                'success': True,
                'license_number': result['license_number'],
                'expiration_date': result['expiration_date']
            }
        else:
            response_data = {
                'success': False,
                'error': 'Could not extract license information. Please ensure the image is clear and contains the required information.'
            }

        return JsonResponse(response_data)

    except Exception as e:
        print(f"Error processing license: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while processing the image. Please try again.'
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

    # Add current datetime for min attribute
    now = timezone.localtime(timezone.now())

    context = {
        'car': car,
        'images': images,
        'features': features,
        'now': now,
    }
    return render(request, 'frontend/car_detail.html', context)


@require_http_methods(["POST"])
def check_car_availability(request):
    try:
        car_id = request.POST.get('car_id')
        rate_type = request.POST.get('rate_type', 'daily')

        car = get_object_or_404(Car, id=car_id)
        now = timezone.localtime(timezone.now())

        # For all rental types, we now use datetime
        start_str = request.POST.get('start_datetime')
        start_datetime = timezone.make_aware(datetime.strptime(start_str, '%Y-%m-%dT%H:%M'))
        duration = int(request.POST.get('duration', 1))

        if rate_type == 'hourly':
            end_datetime = start_datetime + timedelta(hours=duration)
        elif rate_type == 'weekly':
            end_datetime = start_datetime + timedelta(weeks=duration)
        else:  # daily
            end_datetime = start_datetime + timedelta(days=duration)

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
    reservations = Reservation.objects.filter(user=request.user).order_by('-start_datetime')

    # Classify reservations
    for reservation in reservations:
        # Convert datetime to date for comparison if rate_type is not hourly
        if reservation.rate_type == 'hourly':
            start = reservation.start_datetime
            end = reservation.end_datetime
            current = now
        else:
            start = reservation.start_datetime.date()
            end = reservation.end_datetime.date()
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
            # All rental types now use datetime
            start_str = request.POST.get('start_datetime')
            start_datetime = timezone.make_aware(datetime.strptime(start_str, '%Y-%m-%dT%H:%M'))

            if rate_type == 'hourly':
                end_datetime = start_datetime + timedelta(hours=duration)
            elif rate_type == 'weekly':
                end_datetime = start_datetime + timedelta(weeks=duration)
            else:  # daily
                end_datetime = start_datetime + timedelta(days=duration)

            # Get the available total units for the period
            get_available_total_units = car.get_available_total_units(start_datetime, end_datetime)

            if get_available_total_units > 0:
                reservation = Reservation.objects.create(
                    user=request.user,
                    car=car,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
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


# views.py

@login_required
def view_payment(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id, user=request.user)

    if request.method == 'POST':

        try:
            # Get the reference number and amount
            reference_number = request.POST.get('reference_number')
            amount = float(request.POST.get('amount', 0))

            # # Verify the amount matches the reservation total
            # if amount != float(reservation.total_price):
            #     messages.error(request, 'Payment amount does not match the reservation total')
            #     return redirect('payment', reservation_id=reservation_id)

            # Update receipt image if a new one is provided
            if 'receipt_image' in request.FILES:
                receipt_image = request.FILES['receipt_image']
                reservation.receipt_image = receipt_image

            # Update reservation with all fields
            reservation.status = 'paid'
            reservation.reference_number = reference_number
            reservation.amount = amount
            reservation.save()

            messages.success(request, 'Payment processed successfully')
            return redirect('payment_confirmation', reservation_id=reservation_id)

        except Exception as e:
            messages.error(request, f'Error processing payment: {str(e)}')
            return redirect('payment', reservation_id=reservation_id)

    return render(request, 'frontend/payment.html', {'reservation': reservation})


def extract_gcash_info(image_file):
    """
    Extract Reference Number and Total Amount from GCash receipt using OCR.Space API
    """
    url = "https://api.ocr.space/parse/image"
    api_key = settings.OCR_SPACE_API_KEY

    try:
        # Compress and convert image to JPEG
        compressed_image = compress_image(image_file)

        files = {
            'file': ('receipt.jpg', compressed_image, 'image/jpeg')
        }

        payload = {
            'apikey': api_key,
            'language': 'eng',
            'isOverlayRequired': False,
            'detectOrientation': True,
            'scale': True,
            'OCREngine': 2,
            'filetype': 'jpg'
        }

        try:

            response = requests.post(url, files=files, data=payload)
            response.raise_for_status()  # Raise an exception for bad status codes

            result = response.json()

            if result.get('ParsedResults'):
                text = result['ParsedResults'][0]['ParsedText']

                if not text.strip():  # Check if extracted text is empty
                    return None

                lines = text.split('\n')

                # Initialize variables
                ref_number = None
                total_amount = None

                # Method 1: Find Reference Number
                ref_pattern = r'\d{4}\s*\d{3}\s*\d{6}'  # Pattern: XXXX XXX XXXXXX
                for line in lines:
                    if 'ref' in line.lower() or 'reference' in line.lower():
                        ref_match = re.search(ref_pattern, line)
                        if ref_match:
                            ref_number = ref_match.group(0).replace(' ', '')
                            break

                # Method 2: Find Total Amount
                amount_pattern = r'₱\s*([\d,]+\.?\d*)|([\d,]+\.?\d*)'
                for line in lines:
                    if 'total amount' in line.lower() or 'amount' in line.lower():
                        amount_match = re.search(amount_pattern, line)
                        if amount_match:
                            amount_str = amount_match.group(1) or amount_match.group(2)
                            # Remove commas and convert to float
                            total_amount = amount_str.replace(',', '')
                            break

                if not total_amount:  # Alternative method for Total Amount
                    for line in lines:
                        if 'amount sent' in line.lower():
                            next_line_index = lines.index(line) + 1
                            if next_line_index < len(lines):
                                amount_match = re.search(amount_pattern, lines[next_line_index])
                                if amount_match:
                                    amount_str = amount_match.group(1) or amount_match.group(2)
                                    total_amount = amount_str.replace(',', '')
                                    break

                # Only return data if at least one field was found
                if ref_number or total_amount:
                    return {
                        'reference_number': ref_number,
                        'total_amount': total_amount
                    }

            return None

        except requests.RequestException as e:
            print(f"Request error: {str(e)}")
            return None

    except Exception as e:
        print(f"Processing error: {str(e)}")
        return None


@login_required
@require_http_methods(["POST"])
def process_receipt(request):
    if not request.FILES.get('receipt'):
        return JsonResponse({
            'success': False,
            'error': 'No image provided'
        })

    try:
        receipt_image = request.FILES['receipt']

        # Check file type
        allowed_types = ['image/jpeg', 'image/png', 'image/jpg']
        if receipt_image.content_type not in allowed_types:
            return JsonResponse({
                'success': False,
                'error': 'Please upload a JPG or PNG image'
            })

        # Process the image
        result = extract_gcash_info(receipt_image)

        if result and (result['reference_number'] or result['total_amount']):
            response_data = {
                'success': True,
                'reference_number': result['reference_number'],
                'total_amount': result['total_amount']
            }
        else:
            response_data = {
                'success': False,
                'error': 'Could not extract receipt information. Please ensure the image is clear and contains the required information.'
            }

        return JsonResponse(response_data)

    except Exception as e:
        print(f"Error processing receipt: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while processing the image. Please try again.'
        })


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
