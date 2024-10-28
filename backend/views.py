import json
from datetime import datetime, timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.http import require_POST, require_http_methods

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
    total_cars = Car.objects.count()
    total_users = User.objects.filter(is_superuser=False).count()
    total_reservations = Reservation.objects.count()
    revenue = Reservation.objects.filter(status='completed').aggregate(Sum('total_price'))['total_price__sum'] or 0

    context = {
        'total_cars': total_cars,
        'total_users': total_users,
        'total_reservations': total_reservations,
        'revenue': revenue,
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
                user.password = make_password(password1)
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
            username = request.POST['username']
            email = request.POST['email']
            password = request.POST['password']
            phone_number = request.POST.get('phone_number', '')

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

            # Validate password strength
            validate_password(password)

            with transaction.atomic():
                user = User(
                    username=username,
                    email=email,
                    first_name=request.POST['first_name'],
                    last_name=request.POST['last_name'],
                    password=make_password(password)
                )
                user.full_clean()
                user.save()

                profile = UserProfile(
                    user=user,
                    phone_number=phone_number,
                    address=request.POST.get('address', ''),
                    license_number=request.POST.get('license_number', ''),
                    license_expiration=request.POST.get('license_expiration'),
                    license_image=request.FILES.get('license_image')
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
            username = request.POST['username']
            email = request.POST['email']
            phone_number = request.POST.get('phone_number', '')

            # Check if username already exists (excluding the current user)
            if User.objects.filter(username=username).exclude(id=user_id).exists():
                messages.error(request, 'This username is already taken.')

            # Check if email already exists (excluding the current user)
            if User.objects.filter(email=email).exclude(id=user_id).exists():
                messages.error(request, 'This email is already in use.')

            # Check if phone number already exists (excluding the current user)
            if phone_number and UserProfile.objects.filter(phone_number=phone_number).exclude(user_id=user_id).exists():
                messages.error(request, 'This phone number is already registered.')

            with transaction.atomic():
                user.username = username
                user.email = email
                user.first_name = request.POST['first_name']
                user.last_name = request.POST['last_name']

                # If a new password is provided, validate and update it
                new_password = request.POST.get('new_password')
                if new_password:
                    if len(new_password) < 8:
                        messages.error(request, 'New password must be at least 8 characters long.')
                    validate_password(new_password, user)
                    user.set_password(new_password)

                user.full_clean()
                user.save()

                profile, created = UserProfile.objects.get_or_create(user=user)
                profile.phone_number = phone_number
                profile.address = request.POST.get('address', '')
                profile.license_number = request.POST.get('license_number', '')
                license_expiration = request.POST.get('license_expiration')
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
def add_reservation(request):
    users = User.objects.filter(is_superuser=False)
    cars = Car.objects.all()

    if request.method == 'POST':
        user_id = request.POST.get('user')
        car_id = request.POST.get('car')
        rate_type = request.POST.get('rate_type')
        start_datetime = request.POST.get('start_datetime')
        end_datetime = request.POST.get('end_datetime')
        receipt_image = request.FILES.get('receipt_image')
        reference_number = request.POST.get('reference_number')
        amount = request.POST.get('amount')
        status = request.POST.get('status')

        try:
            # Get car and check total units
            car = Car.objects.get(id=car_id)
            if car.total_units <= 0:
                messages.error(request, 'No units available for this car model.')
                return redirect('admin_reservations')

            # Convert string dates to datetime objects
            start_datetime = datetime.strptime(start_datetime, '%Y-%m-%d').date()
            end_datetime = datetime.strptime(end_datetime, '%Y-%m-%d').date()

            # Check availability
            if car.is_available(start_datetime, end_datetime):
                # Calculate duration
                duration = (end_datetime - start_datetime).days

                # Calculate total price based on rate type
                if rate_type == 'hourly':
                    total_price = (duration * 24) * car.hourly_rate
                elif rate_type == 'daily':
                    total_price = duration * car.daily_rate
                elif rate_type == 'weekly':
                    weeks = (duration + 6) // 7  # Rounds up to nearest week
                    total_price = weeks * car.weekly_rate
                else:
                    total_price = 0

                # Create reservation
                reservation = Reservation.objects.create(
                    user_id=user_id,
                    car_id=car_id,
                    rate_type=rate_type,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    receipt_image=receipt_image,
                    reference_number=reference_number,
                    amount=amount,
                    status=status,
                    total_price=total_price
                )

                messages.success(request, 'Reservation created successfully.')
                return redirect('admin_reservations')
            else:
                messages.error(request, 'Car is not available for the selected dates.')
                return redirect('admin_reservations')

        except Car.DoesNotExist:
            messages.error(request, 'Selected car does not exist.')
            return redirect('admin_reservations')
        except ValueError as e:
            messages.error(request, f'Invalid date format: {str(e)}')
            return redirect('admin_reservations')
        except Exception as e:
            messages.error(request, f'An error occurred: {str(e)}')
            return redirect('admin_reservations')

    context = {
        'users': users,
        'cars': cars,
        'statuses': Reservation.STATUS_CHOICES,
        'rate_types': Reservation.RATE_TYPES,
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
        start_datetime = request.POST.get('start_datetime')
        end_datetime = request.POST.get('end_datetime')
        new_receipt_image = request.FILES.get('receipt_image')
        reference_number = request.POST.get('reference_number')
        amount = request.POST.get('amount')
        status = request.POST.get('status')

        try:
            # Convert string dates to datetime objects
            start_datetime = datetime.strptime(start_datetime, '%Y-%m-%d').date()
            end_datetime = datetime.strptime(end_datetime, '%Y-%m-%d').date()

            # Get the car
            car = Car.objects.get(id=car_id)

            # Calculate duration
            duration = (end_datetime - start_datetime).days

            # Calculate total price based on rate type
            if rate_type == 'hourly':
                total_price = (duration * 24) * car.hourly_rate
            elif rate_type == 'daily':
                total_price = duration * car.daily_rate
            elif rate_type == 'weekly':
                weeks = (duration + 6) // 7  # Rounds up to nearest week
                total_price = weeks * car.weekly_rate
            else:
                total_price = 0

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
            reservation.status = status
            reservation.total_price = total_price
            reservation.save()

            messages.success(request, 'Reservation updated successfully.')
            return redirect('admin_reservations')

        except Car.DoesNotExist:
            messages.error(request, 'Selected car does not exist.')
            return redirect('admin_reservations')
        except ValueError as e:
            messages.error(request, f'Invalid date format: {str(e)}')
            return redirect('admin_reservations')
        except Exception as e:
            messages.error(request, f'An error occurred: {str(e)}')
            return redirect('admin_reservations')

    context = {
        'reservation': reservation,
        'users': users,
        'cars': cars,
        'statuses': Reservation.STATUS_CHOICES,
        'rate_types': Reservation.RATE_TYPES,
    }
    return render(request, 'backend/edit_reservation.html', context)


@admin_required
@require_POST
def cancel_reservation(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)
    if reservation.status != 'cancelled':
        reservation.status = 'cancelled'
        reservation.save()
        messages.success(request, 'Reservation cancelled successfully.')

        return redirect('admin_reservations')


@admin_required
@require_POST
def delete_reservation(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)
    reservation.delete()

    messages.success(request, f'The reservation for { reservation.car.brand } { reservation.car.model } has been successfully deleted.')
    return redirect('admin_reservations')


@admin_required
def view_payments(request):
    payment_list = Reservation.objects.filter(status='paid').order_by('-updated_at')
    paginator = Paginator(payment_list, 10)  # Show 10 payments per page
    page = request.GET.get('page')
    payments = paginator.get_page(page)  # This handles all edge cases automatically
    return render(request, 'backend/payments.html', {'payments': payments})


@admin_required
def view_profile(request):
    if request.method == 'POST':
        # Handle profile update
        user = request.user
        user.first_name = request.POST['first_name']
        user.last_name = request.POST['last_name']
        user.email = request.POST['email']
        user.save()
        messages.success(request, 'Your profile has been updated successfully.')
        return redirect('admin_profile')

    return render(request, 'backend/profile.html')
