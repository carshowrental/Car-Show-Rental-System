import json
from datetime import datetime, timedelta
from functools import wraps
import re
import requests
from PIL import Image
import io
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum, Count
from django.db.models.functions import ExtractMonth
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.http import require_POST, require_http_methods
from sympy.physics.units import amount

from backend.models import Car, Reservation, CarImage, UserProfile, PasswordResetToken


def admin_required(view_func):
    """
    Decorator for views that checks that the user is an admin,
    redirecting to the admin login page if necessary.
    """

    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        is_admin = request.user.is_authenticated and request.user.is_staff

        if not is_admin:
            messages.error(request, 'Please login with admin credentials to access this page.')
            return redirect('admin_login')
        return view_func(request, *args, **kwargs)

    return _wrapped_view


@admin_required
def view_dashboard(request):
    # Base statistics
    total_cars = Car.objects.count()
    total_users = User.objects.filter(is_superuser=False).count()
    total_reservations = Reservation.objects.count()
    revenue = Reservation.objects.filter(status='completed').aggregate(Sum('total_price'))['total_price__sum'] or 0

    # Recent reservations
    recent_reservations = (
        Reservation.objects
        .select_related('user', 'car')
        .order_by('-created_at')[:5]
    )

    # Popular cars
    popular_cars = (
        Car.objects
        .annotate(total_rentals=Count('reservation'))
        .order_by('-total_rentals')[:5]
    )

    # Get data for Reservations Line Chart
    current_year = timezone.localtime(timezone.now()).year
    reservations_by_month = (
        Reservation.objects
        .filter(created_at__year=current_year)
        .annotate(month=ExtractMonth('created_at'))
        .values('month')
        .annotate(count=Count('id'))
        .order_by('month')
    )

    # Create a list of all months with 0 counts for months without reservations
    months_data = {i: 0 for i in range(1, 13)}
    for item in reservations_by_month:
        months_data[item['month']] = item['count']

    # Format data for the chart
    months_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    reservations_data = [months_data[i] for i in range(1, 13)]

    # Get data for Revenue Pie Chart - Fixed version
    revenue_data = {
        'Hourly': Reservation.objects.filter(status='completed', rate_type='hourly').aggregate(Sum('total_price'))[
                      'total_price__sum'] or 0,
        'Daily': Reservation.objects.filter(status='completed', rate_type='daily').aggregate(Sum('total_price'))[
                     'total_price__sum'] or 0,
        'Weekly': Reservation.objects.filter(status='completed', rate_type='weekly').aggregate(Sum('total_price'))[
                      'total_price__sum'] or 0
    }

    # Remove rate types with 0 revenue and convert to lists
    revenue_by_type = {k: float(v) for k, v in revenue_data.items() if v > 0}
    revenue_labels = list(revenue_by_type.keys())
    revenue_values = list(revenue_by_type.values())

    context = {
        'total_cars': total_cars,
        'total_users': total_users,
        'total_reservations': total_reservations,
        'revenue': revenue,
        'recent_reservations': recent_reservations,
        'popular_cars': popular_cars,
        # Chart data
        'months_labels': json.dumps(months_labels),
        'reservations_data': json.dumps(reservations_data),
        'revenue_labels': json.dumps(revenue_labels),
        'revenue_data': json.dumps(revenue_values)
    }
    return render(request, 'backend/dashboard.html', context)


@require_http_methods(["GET", "POST"])
def admin_login(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_staff:
            login(request, user)
            return redirect('admin_dashboard')  # Redirect to admin dashboard
        else:
            messages.error(request, 'Invalid username or password, or insufficient permissions.')
    return render(request, 'backend/login.html')


def admin_logout(request):
    logout(request)
    return redirect('admin_login')


def forgot_password(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            user = User.objects.get(email=email, is_staff=True)
            token = PasswordResetToken.objects.create(
                user=user,
                expires_at=timezone.localtime(timezone.now()) + timedelta(hours=24)
            )

            reset_url = request.build_absolute_uri(
                reverse('admin_reset_password', args=[str(token.token)])
            )

            subject = 'Admin Password Reset for Car Show Rental'
            html_message = render_to_string('backend/reset_password_email.html', {
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
            return redirect('admin_login')
        except User.DoesNotExist:
            messages.error(request, 'No admin user with that email address exists.')

    return render(request, 'backend/forgot_password.html')


def reset_password(request, token):
    try:
        reset_token = PasswordResetToken.objects.get(token=token)

        # Verify this is an admin user
        if not reset_token.user.is_staff:
            messages.error(request, 'Invalid password reset link.')
            return redirect('admin_login')

        # Check if token is expired
        if not reset_token.is_valid():
            messages.error(request, 'This password reset link has expired.')
            return redirect('admin_login')

        if request.method == 'POST':
            password1 = request.POST.get('password1')
            password2 = request.POST.get('password2')

            if password1 != password2:
                messages.error(request, 'Passwords do not match.')
            elif len(password1) < 8:
                messages.error(request, 'Password must be at least 8 characters long.')
            else:
                user = reset_token.user
                user.set_password(password1)
                user.save()
                reset_token.delete()
                messages.success(request,
                                 'Your password has been reset successfully. You can now log in with your new password.')
                return redirect('admin_login')

        return render(request, 'backend/reset_password.html', {'token': token})

    except PasswordResetToken.DoesNotExist:
        messages.error(request, 'Invalid password reset link.')
        return redirect('admin_login')


@admin_required
def view_cars(request):
    car_list = Car.objects.all()
    paginator = Paginator(car_list, 10)  # Show 10 cars per page
    page = request.GET.get('page')
    cars = paginator.get_page(page)  # This handles all edge cases automatically
    return render(request, 'backend/cars.html', {'cars': cars})


@admin_required
def car_detail(request, car_id):
    car = get_object_or_404(Car, id=car_id)
    reservation_list = car.reservation_set.all().order_by('-start_datetime')
    paginator = Paginator(reservation_list, 5)  # Show 5 reservations per page
    page = request.GET.get('page')
    reservations = paginator.get_page(page)

    # Split the features string into a list, respecting newlines
    features = [feature.strip() for feature in car.features.split('\n') if feature.strip()]

    context = {
        'car': car,
        'reservations': reservations,
        'features': features
    }

    return render(request, 'backend/car_detail.html', context)


@admin_required
@require_http_methods(["GET", "POST"])
def add_car(request):
    if request.method == 'POST':
        try:
            # Handle form submission
            brand = request.POST.get('brand')
            model = request.POST.get('model')
            year = request.POST.get('year')
            car_type = request.POST.get('car_type')
            total_units = request.POST.get('total_units')
            hourly_rate = request.POST.get('hourly_rate')
            daily_rate = request.POST.get('daily_rate')
            features = request.POST.get('features')

            # Validate required fields
            if not all([brand, model, year, car_type, total_units, hourly_rate, daily_rate]):
                messages.warning(request, 'Missing required fields')

            car = Car.objects.create(
                brand=brand,
                model=model,
                year=int(year),
                car_type=car_type,
                total_units=int(total_units),
                hourly_rate=float(hourly_rate),
                daily_rate=float(daily_rate),
                features=features
            )

            # Handle multiple image uploads
            images = request.FILES.getlist('car_images[]')
            main_image_index = int(request.POST.get('main_image', 0))

            for i, image in enumerate(images):
                CarImage.objects.create(
                    car=car,
                    image=image,
                    is_main=(i == main_image_index)
                )

            messages.success(request, f'Car {car.brand} {car.model} has been added successfully.')
            return JsonResponse({'success': True, 'redirect': reverse('admin_cars')})

        except ValidationError as e:
            messages.error(request, str(e))
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
        except Exception as e:
            messages.error(request, 'An unexpected error occurred. Please try again.')
            return JsonResponse({'success': False, 'error': 'An unexpected error occurred.'}, status=500)

    # If GET request, render the form
    return render(request, 'backend/add_car.html', {'car_types': Car.CAR_TYPES})


@admin_required
@require_http_methods(["GET", "POST"])
def edit_car(request, car_id):
    car = get_object_or_404(Car, id=car_id)

    if request.method == 'POST':
        try:
            # Update car details
            car.brand = request.POST.get('brand')
            car.model = request.POST.get('model')
            car.year = int(request.POST.get('year'))
            car.car_type = request.POST.get('car_type')
            car.total_units = int(request.POST.get('total_units'))
            car.unavailable_units = int(request.POST.get('unavailable_units'))
            car.hourly_rate = float(request.POST.get('hourly_rate'))
            car.daily_rate = float(request.POST.get('daily_rate'))
            car.features = request.POST.get('features')
            car.save()

            # Handle image deletions
            deleted_images = json.loads(request.POST.get('deleted_images', '[]'))
            CarImage.objects.filter(id__in=deleted_images).delete()

            # Handle new image uploads
            new_images = request.FILES.getlist('new_images[]')
            for image in new_images:
                CarImage.objects.create(car=car, image=image)

            # Set main image
            main_image_id = request.POST.get('main_image_id')
            if main_image_id:
                CarImage.objects.filter(car=car).update(is_main=False)
                CarImage.objects.filter(id=main_image_id).update(is_main=True)

            return JsonResponse({
                'success': True,
                'message': f'Car {car.brand} {car.model} has been updated successfully.',
                'redirect': reverse('admin_cars')
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

    # If GET request, render the form with car data
    context = {
        'car': car,
        'car_types': Car.CAR_TYPES,
        'images': car.carimages_set.all(),
    }
    return render(request, 'backend/edit_car.html', context)


@require_POST
def delete_car(request, car_id):
    car = get_object_or_404(Car, id=car_id)
    brand_model = f"{car.brand} {car.model}"
    car.delete()
    messages.success(request, f'Car {brand_model} has been successfully deleted.')
    return redirect('admin_cars')


@login_required
@admin_required
def view_user_accounts(request):
    user_list = User.objects.filter(is_superuser=False)
    paginator = Paginator(user_list, 10)  # Show 10 users per page
    page = request.GET.get('page')
    users = paginator.get_page(page)  # This handles all edge cases automatically
    return render(request, 'backend/user_accounts.html', {'users': users})


@login_required
@admin_required
def add_user(request):
    if request.method == 'POST':
        try:
            username = request.POST.get('username')
            email = request.POST.get('email')
            phone_number = request.POST.get('phone_number')
            address = request.POST.get('address')
            password = request.POST.get('password')
            confirm_password = request.POST.get('confirm_password')
            license_image=request.FILES.get('license_image')
            full_name = request.POST.get('full_name')
            license_number = request.POST.get('license_number')
            license_expiration = request.POST.get('license_expiration')

            # Check if username already exists
            if User.objects.filter(username=username).exists():
                messages.error(request, 'This username is already taken.')

            # Check if email already exists
            if User.objects.filter(email=email).exists():
                messages.error(request, 'This email is already in use.')

            # Check if phone number already exists
            if phone_number and UserProfile.objects.filter(phone_number=phone_number).exists():
                messages.error(request, 'This phone number is already registered.')

            # Validate password length
            if len(password) < 8:
                messages.error(request, 'Password must be at least 8 characters long.')

            # Check if password match
            if password != confirm_password:
                messages.error(request, 'Password do not match.')

            # Validate password strength
            validate_password(password)

            with transaction.atomic():
                user = User(
                    username=username,
                    email=email
                )
                user.set_password(password)
                user.full_clean()
                user.save()

                profile = UserProfile(
                    user=user,
                    phone_number=phone_number,
                    address=address,
                    full_name=full_name,
                    license_image=license_image,
                    license_number=license_number,
                    license_expiration=license_expiration
                )
                profile.full_clean()
                profile.save()

            messages.success(request, f'User {user.username} has been added successfully.')
            return redirect('admin_user_accounts')
        except ValidationError as e:
            messages.error(request, f'Error adding user: {e}')

    return render(request, 'backend/add_user.html')


@login_required
@admin_required
def edit_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        try:
            username = request.POST.get('username')
            email = request.POST.get('email')
            phone_number = request.POST.get('phone_number')
            address = request.POST.get('address')
            new_password = request.POST.get('password')
            confirm_password = request.POST.get('confirm_password')
            license_image=request.FILES.get('license_image')
            full_name = request.POST.get('full_name')
            license_number = request.POST.get('license_number')
            license_expiration = request.POST.get('license_expiration')

            # Check if username already exists (excluding the current user)
            if User.objects.filter(username=username).exclude(id=user_id).exists():
                messages.error(request, 'This username is already taken.')

            # Check if email already exists (excluding the current user)
            if User.objects.filter(email=email).exclude(id=user_id).exists():
                messages.error(request, 'This email is already in use.')

            # Check if phone number already exists (excluding the current user)
            if phone_number and UserProfile.objects.filter(phone_number=phone_number).exclude(user_id=user_id).exists():
                messages.error(request, 'This phone number is already registered.')

            if new_password:
                # Check if password match
                if new_password != confirm_password:
                    messages.error(request, 'Password do not match.')

            with transaction.atomic():
                user.username = username
                user.email = email

                # If a new password is provided, validate and update it
                if new_password:
                    if len(new_password) < 8:
                        messages.error(request, 'New password must be at least 8 characters long.')
                    validate_password(new_password, user)
                    user.set_password(new_password)

                user.full_clean()
                user.save()

                profile, created = UserProfile.objects.get_or_create(user=user)
                profile.phone_number = phone_number
                profile.address = address
                profile.full_name = full_name
                profile.license_number = license_number
                if license_expiration:
                    profile.license_expiration = datetime.strptime(license_expiration, '%Y-%m-%d').date()
                if 'license_image' in request.FILES:
                    profile.license_image = request.FILES['license_image']
                profile.full_clean()
                profile.save()

            messages.success(request, f'User {user.username} has been updated successfully.')
            return redirect('admin_user_accounts')
        except ValidationError as e:
            messages.error(request, f'Error updating user: {e}')

    return render(request, 'backend/edit_user.html', {'user': user})


@login_required
@admin_required
@require_POST
def delete_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    user.delete()
    messages.success(request, f'User {user.username} has been permanently deleted.')
    return redirect('admin_user_accounts')


@admin_required
def view_reservations(request):
    reservation_list = Reservation.objects.all().order_by('-created_at')
    paginator = Paginator(reservation_list, 10)  # Show 10 reservations per page
    page = request.GET.get('page')
    reservations = paginator.get_page(page)  # This handles all edge cases automatically
    return render(request, 'backend/reservations.html', {'reservations': reservations})


@admin_required
@require_http_methods(["POST"])
def admin_check_availability(request):
    try:
        car_id = request.POST.get('car_id')
        rate_type = request.POST.get('rate_type')
        start_datetime_str = request.POST.get('start_datetime')
        duration = int(request.POST.get('duration', 1))
        reservation_id = request.POST.get('reservation_id')

        car = get_object_or_404(Car, id=car_id)
        start_datetime = timezone.make_aware(datetime.strptime(start_datetime_str, '%Y-%m-%dT%H:%M'))

        # Calculate end datetime
        if rate_type == 'hourly':
            end_datetime = start_datetime + timedelta(hours=duration)
        elif rate_type == 'daily':
            end_datetime = start_datetime + timedelta(days=duration)
        else:  # weekly
            end_datetime = start_datetime + timedelta(weeks=duration)

        # Validate dates/times
        if start_datetime < timezone.localtime(timezone.now()):
            return JsonResponse({
                'available': False,
                'message': 'Cannot book in the past'
            })

        # Get all overlapping reservations
        overlapping_reservations = Reservation.objects.filter(
            car=car,
            status__in=['pending', 'partial', 'paid', 'active'],
            start_datetime__lt=end_datetime,
            end_datetime__gt=start_datetime
        )

        # If this is an edit, exclude the current reservation from the count
        if reservation_id:
            overlapping_reservations = overlapping_reservations.exclude(id=reservation_id)

        # Count overlapping reservations
        reserved_units = overlapping_reservations.count()
        available_units = max(0, car.available_units - reserved_units)

        return JsonResponse({
            'available': available_units > 0,
            'get_available_total_units': available_units,
            'message': f'{available_units} units available' if available_units > 0 else 'No units available for these dates/times'
        })

    except Exception as e:
        return JsonResponse({
            'available': False,
            'message': str(e)
        }, status=400)


@admin_required
def add_reservation(request):
    users = User.objects.filter(is_superuser=False)
    cars = Car.objects.all()

    if request.method == 'POST':
        user_id = request.POST.get('user')
        car_id = request.POST.get('car')
        rate_type = request.POST.get('rate_type')
        start_datetime_str = request.POST.get('start_datetime')
        duration = int(request.POST.get('duration', 1))
        status = request.POST.get('status')

        try:
            with transaction.atomic():
                # Get car with lock for atomic operation
                car = Car.objects.select_for_update().get(id=car_id)

                # Convert and validate datetime
                start_datetime = timezone.make_aware(datetime.strptime(start_datetime_str, '%Y-%m-%dT%H:%M'))

                # Calculate end_datetime based on rate_type and duration
                if rate_type == 'hourly':
                    end_datetime = start_datetime + timedelta(hours=duration)
                    total_price = duration * car.hourly_rate
                elif rate_type == 'daily':
                    end_datetime = start_datetime + timedelta(days=duration)
                    total_price = duration * car.daily_rate
                elif rate_type == 'weekly':
                    end_datetime = start_datetime + timedelta(weeks=duration)
                    total_price = duration * car.weekly_rate
                else:
                    raise ValueError("Invalid rate type")

                # Calculate amount based on status
                if status == 'paid':
                    amount = total_price
                elif status == 'partial':
                    amount = total_price / 2

                # Create reservation
                reservation = Reservation.objects.create(
                    user_id=user_id,
                    car_id=car_id,
                    rate_type=rate_type,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    amount=amount,
                    status=status,
                    total_price=total_price
                )

                messages.success(request, 'Reservation created successfully.')
                return redirect('admin_reservations')

        except Car.DoesNotExist:
            messages.error(request, 'Selected car does not exist.')
        except ValueError as e:
            messages.error(request, f'Invalid date format: {str(e)}')
        except Exception as e:
            messages.error(request, f'An error occurred: {str(e)}')

        return redirect('admin_reservations')

    context = {
        'users': users,
        'cars': cars,
        'rate_types': Reservation.RATE_TYPES,
        'now': timezone.localtime(timezone.now()),
    }
    return render(request, 'backend/add_reservation.html', context)


@admin_required
def edit_reservation(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)
    users = User.objects.filter(is_superuser=False)
    cars = Car.objects.all()

    if request.method == 'POST':
        user_id = request.POST.get('user')
        car_id = request.POST.get('car')
        rate_type = request.POST.get('rate_type')
        start_datetime_str = request.POST.get('start_datetime')
        duration = int(request.POST.get('duration', 1))
        new_receipt_image = request.FILES.get('receipt_image')
        reference_number = request.POST.get('reference_number')
        new_status = request.POST.get('status')  # Get the new status from POST data

        try:
            with transaction.atomic():
                # Get car with lock for atomic operation
                car = Car.objects.select_for_update().get(id=car_id)

                # Convert and validate datetime
                start_datetime = timezone.make_aware(datetime.strptime(start_datetime_str, '%Y-%m-%dT%H:%M'))

                # Calculate end_datetime and total_price based on rate_type and duration
                if rate_type == 'hourly':
                    end_datetime = start_datetime + timedelta(hours=duration)
                    total_price = duration * car.hourly_rate
                elif rate_type == 'daily':
                    end_datetime = start_datetime + timedelta(days=duration)
                    total_price = duration * car.daily_rate
                elif rate_type == 'weekly':
                    end_datetime = start_datetime + timedelta(weeks=duration)
                    total_price = duration * car.weekly_rate
                else:
                    raise ValueError("Invalid rate type")

                # Calculate amount based on status
                if new_status == 'paid':
                    amount = total_price
                elif new_status == 'partial':
                    amount = total_price / 2
                else:  # pending
                    amount = reservation.amount

                # Handle receipt image update
                if new_receipt_image:
                    # Delete old receipt image if it exists
                    if reservation.receipt_image:
                        reservation.receipt_image.delete(save=False)
                    reservation.receipt_image = new_receipt_image

                # Update reservation
                reservation.user_id = user_id
                reservation.car_id = car_id
                reservation.rate_type = rate_type
                reservation.start_datetime = start_datetime
                reservation.end_datetime = end_datetime
                reservation.reference_number = reference_number
                reservation.amount = amount
                reservation.status = new_status
                reservation.total_price = total_price
                reservation.save()

                # If the submitted status is 'completed', send SMS
                if new_status == 'completed':
                    try:
                        # Get user's phone number
                        user_profile = reservation.user.userprofile
                        if user_profile.phone_number:
                            # Prepare message
                            message = (
                                f"Your reservation for {reservation.car.brand} {reservation.car.model} has been completed.\n\n"
                                f"Thank you for choosing our service!\n\n"
                                f"- Car Show Car Rental Team"
                            )

                            # Send SMS using Semaphore
                            payload = {
                                'apikey': settings.SEMAPHORE_API_KEY,
                                'number': user_profile.phone_number,
                                'message': message,
                                'sendername': settings.SEMAPHORE_SENDER_NAME
                            }
                            response = requests.post('https://api.semaphore.co/api/v4/messages', json=payload)

                            if response.status_code == 200:
                                messages.success(request, 'Reservation marked as completed and notification sent to user.')
                            else:
                                messages.warning(request, 'Reservation marked as completed but notification failed to send.')
                    except Exception as e:
                        print(f"SMS sending failed: {str(e)}")
                        messages.warning(request, 'Reservation marked as completed but notification failed to send.')
                else:
                    messages.success(request, 'Reservation updated successfully.')

                # Update the reservation status after SMS attempt
                reservation.status = new_status
                reservation.save()

                return redirect('admin_reservations')

        except Car.DoesNotExist:
            messages.error(request, 'Selected car does not exist.')
        except ValueError as e:
            messages.error(request, f'Invalid date format: {str(e)}')
        except Exception as e:
            messages.error(request, f'An error occurred: {str(e)}')

    # Calculate current duration based on start and end datetime
    if reservation.rate_type == 'hourly':
        current_duration = int((reservation.end_datetime - reservation.start_datetime).total_seconds() / 3600)
    elif reservation.rate_type == 'daily':
        current_duration = (reservation.end_datetime - reservation.start_datetime).days
    else:  # weekly
        current_duration = (reservation.end_datetime - reservation.start_datetime).days // 7

    context = {
        'reservation': reservation,
        'users': users,
        'cars': cars,
        'current_duration': current_duration,
        'rate_types': Reservation.RATE_TYPES,
        'statuses': Reservation.STATUS_CHOICES,
        'now': timezone.localtime(timezone.now()),
    }
    return render(request, 'backend/edit_reservation.html', context)


@admin_required
@require_POST
def delete_reservation(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)
    reservation.delete()

    messages.success(request,
                     f'The reservation for {reservation.car.brand} {reservation.car.model} has been successfully deleted.')
    return redirect('admin_reservations')


@admin_required
def view_payments(request):
    payment_list = Reservation.objects.filter(status__in=['paid', 'partial'])
    paginator = Paginator(payment_list, 10)  # Show 10 payments per page
    page = request.GET.get('page')
    payments = paginator.get_page(page)  # This handles all edge cases automatically
    return render(request, 'backend/payments.html', {'payments': payments})


@admin_required
def view_profile(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_profile':
            # Handle profile update
            user = request.user
            user.first_name = request.POST['firstName']
            user.last_name = request.POST['lastName']
            email = request.POST['email']

            # Validate email is not already taken
            if email != user.email:
                if user.__class__.objects.filter(email=email).exists():
                    messages.error(request, 'This email is already in use.')
                    return redirect('admin_profile')
                user.email = email

            user.save()
            messages.success(request, 'Your profile has been updated successfully.')

        elif action == 'change_password':
            current_password = request.POST.get('currentPassword')
            new_password = request.POST.get('newPassword')
            confirm_password = request.POST.get('confirmPassword')

            # Validate current password
            if not check_password(current_password, request.user.password):
                messages.error(request, 'Current password is incorrect.')
                return redirect('admin_profile')

            # Validate new password
            if new_password != confirm_password:
                messages.error(request, 'New passwords do not match.')
                return redirect('admin_profile')

            if len(new_password) < 8:
                messages.error(request, 'Password must be at least 8 characters long.')
                return redirect('admin_profile')

            # Update password
            try:
                user = request.user
                user.set_password(new_password)
                user.save()

                messages.success(request, 'Your password was successfully updated!')
            except Exception as e:
                messages.error(request, f'Error changing password: {str(e)}')

        return redirect('admin_profile')

    return render(request, 'backend/profile.html')

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
                full_name = None
                license_number = None
                expiration_date = None

                # Method 1: Find by license number pattern and check next date
                license_pattern = r'[A-Z]\d{2}-\d{2}-\d{6}'
                date_pattern = r'\d{4}/\d{2}/\d{2}'

                # Method to extract full name
                for i, line in enumerate(lines):
                    # Look for "Last Name, First Name, Middle Name" or after "Name:" label
                    if 'last name' in line.lower() or 'name:' in line.lower():
                        # Check next line for the actual name
                        if i + 1 < len(lines):
                            name_line = lines[i + 1].strip()
                            # Remove any common prefixes/labels
                            name_line = re.sub(r'^(Name:|Last Name:|Full Name:)', '', name_line, flags=re.IGNORECASE)
                            # Clean and format the name
                            full_name = name_line.strip().upper()

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

                # Alternative method for full name if not found
                if not full_name:
                    # Look for typical name patterns (ALL CAPS with commas)
                    name_pattern = r'([A-Z]+,\s*[A-Z\s]+(?:,[A-Z\s]+)?)'
                    for line in lines:
                        name_match = re.search(name_pattern, line)
                        if name_match and ',' in line:  # Ensure it contains a comma to avoid false positives
                            full_name = name_match.group(0).strip()
                            break

                # Only return data if at least one field was found
                if license_number or expiration_date or full_name:
                    return {
                        'license_number': license_number,
                        'expiration_date': expiration_date,
                        'full_name': full_name
                    }

            return None

        except requests.RequestException as e:
            print(f"Request error: {str(e)}")
            return None

    except Exception as e:
        print(f"Processing error: {str(e)}")
        return None


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

        if result and (result['full_name'] or result['license_number'] or result['expiration_date']):
            response_data = {
                'success': True,
                'full_name': result['full_name'],
                'license_number': result['license_number'],
                'expiration_date': result['expiration_date'],
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
