from datetime import datetime

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import User
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST, require_http_methods

from backend.models import Car, Reservation, CarImage


def is_admin(user):
    return user.is_authenticated and user.is_staff


@require_http_methods(["GET", "POST"])
def admin_login(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_staff:
            login(request, user)
            return redirect('dashboard')  # Redirect to admin dashboard
        else:
            messages.error(request, 'Invalid username or password, or insufficient permissions.')
    return render(request, 'admin_login.html')


def admin_logout(request):
    logout(request)
    return redirect('admin_login')


@user_passes_test(is_admin)
def dashboard(request):
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
    return render(request, 'dashboard.html', context)


@user_passes_test(is_admin)
def car_list(request):
    cars = Car.objects.all()
    return render(request, 'admin_car_list.html', {'cars': cars})


@user_passes_test(is_admin)
def car_detail(request, car_id):
    car = get_object_or_404(Car, id=car_id)
    return render(request, 'admin_car_detail.html', {'car': car})


@user_passes_test(is_admin)
def add_car(request):
    if request.method == 'POST':
        # Handle form submission
        brand = request.POST['brand']
        model = request.POST['model']
        year = request.POST['year']
        car_type = request.POST['car_type']
        price_per_day = request.POST['price_per_day']
        features = request.POST['features']

        car = Car.objects.create(
            brand=brand,
            model=model,
            year=year,
            car_type=car_type,
            price_per_day=price_per_day,
            features=features
        )

        # Handle multiple image uploads
        images = request.FILES.getlist('images')
        for i, image in enumerate(images):
            CarImage.objects.create(
                car=car,
                image=image,
                is_main=(i == 0)  # Set the first image as the main image
            )

        messages.success(request, f'Car {car.brand} {car.model} has been added successfully.')
        return redirect('admin_car_list')

    car_types = Car.CAR_TYPES
    return render(request, 'add_car.html', {'car_types': car_types})


@user_passes_test(is_admin)
def edit_car(request, car_id):
    car = get_object_or_404(Car, id=car_id)

    if request.method == 'POST':
        # Update car details
        car.brand = request.POST['brand']
        car.model = request.POST['model']
        car.year = request.POST['year']
        car.car_type = request.POST['car_type']
        car.price_per_day = request.POST['price_per_day']
        car.features = request.POST['features']
        car.save()

        # Handle image uploads
        new_images = request.FILES.getlist('new_images')
        for image in new_images:
            CarImage.objects.create(car=car, image=image)

        # Handle image deletions
        images_to_delete = request.POST.getlist('delete_images')
        CarImage.objects.filter(id__in=images_to_delete).delete()

        # Set main image
        main_image_id = request.POST.get('main_image')
        if main_image_id:
            CarImage.objects.filter(car=car).update(is_main=False)
            CarImage.objects.filter(id=main_image_id).update(is_main=True)

        messages.success(request, f'Car {car.brand} {car.model} has been updated successfully.')
        return redirect('admin_car_list')

    car_types = Car.CAR_TYPES
    context = {
        'car': car,
        'car_types': car_types,
        'images': car.carimages_set.all(),
    }
    return render(request, 'edit_car.html', context)


@require_POST
def delete_car(request, car_id):
    car = get_object_or_404(Car, id=car_id)
    car.delete()
    return JsonResponse({'status': 'success'})


@user_passes_test(is_admin)
def user_accounts(request):
    users = User.objects.filter(is_superuser=False)
    return render(request, 'user_accounts.html', {'users': users})


@user_passes_test(is_admin)
def add_user(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']
        first_name = request.POST['first_name']
        last_name = request.POST['last_name']

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
        messages.success(request, f'User {user.username} has been added successfully.')
        return redirect('user_accounts')

    return render(request, 'add_user.html')


@user_passes_test(is_admin)
def edit_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')

        user.username = username
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.save()

        messages.success(request, 'User updated successfully.')
        return redirect('user_accounts')

    return render(request, 'edit_user.html', {'user': user})


@user_passes_test(is_admin)
@require_POST
def delete_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    user.delete()
    return JsonResponse({'status': 'success'})


@user_passes_test(is_admin)
def reservations(request):
    reservations = Reservation.objects.all().order_by('-created_at')
    return render(request, 'admin_reservations.html', {'reservations': reservations})


@user_passes_test(is_admin)
def add_reservation(request):
    users = User.objects.filter(is_superuser=False)
    cars = Car.objects.all()

    if request.method == 'POST':
        user_id = request.POST.get('user')
        car_id = request.POST.get('car')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        status = request.POST.get('status')

        # Convert string dates to datetime objects
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

        # Calculate total price
        car = Car.objects.get(id=car_id)
        days = (end_date - start_date).days + 1
        total_price = car.price_per_day * days

        reservation = Reservation.objects.create(
            user_id=user_id,
            car_id=car_id,
            start_date=start_date,
            end_date=end_date,
            status=status,
            total_price=total_price
        )

        messages.success(request, 'Reservation created successfully.')
        return redirect('admin_reservations')

    context = {
        'users': users,
        'cars': cars,
        'statuses': Reservation.STATUS_CHOICES
    }
    return render(request, 'admin_add_reservation.html', context)


@user_passes_test(is_admin)
def edit_reservation(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)
    users = User.objects.filter(is_superuser=False)
    cars = Car.objects.all()

    if request.method == 'POST':
        user_id = request.POST.get('user')
        car_id = request.POST.get('car')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        status = request.POST.get('status')

        reservation.user_id = user_id
        reservation.car_id = car_id
        reservation.start_date = start_date
        reservation.end_date = end_date
        reservation.status = status
        reservation.save()

        messages.success(request, 'Reservation updated successfully.')
        return redirect('admin_reservations')

    context = {
        'reservation': reservation,
        'users': users,
        'cars': cars,
        'statuses': Reservation.STATUS_CHOICES
    }
    return render(request, 'admin_edit_reservation.html', context)


@user_passes_test(is_admin)
@require_POST
def cancel_reservation(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)
    if reservation.status != 'cancelled':
        reservation.status = 'cancelled'
        reservation.save()
        messages.success(request, 'Reservation cancelled successfully.')
    return JsonResponse({'status': 'success'})


@user_passes_test(is_admin)
def payment_history(request):
    payments = Reservation.objects.filter(status='paid').order_by('-updated_at')
    return render(request, 'admin_payment_history.html', {'payments': payments})


@user_passes_test(is_admin)
def profile(request):
    if request.method == 'POST':
        # Handle profile update
        user = request.user
        user.first_name = request.POST['first_name']
        user.last_name = request.POST['last_name']
        user.email = request.POST['email']
        user.save()
        messages.success(request, 'Your profile has been updated successfully.')
        return redirect('admin_profile')

    return render(request, 'admin_profile.html')
