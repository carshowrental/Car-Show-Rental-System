import uuid

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Car(models.Model):
    CAR_TYPES = [
        ('sedan', 'Sedan'),
        ('suv', 'SUV'),
        ('pick up', 'Pick Up'),
        ('van', 'Van'),
        ('mini van', 'Mini Van'),
    ]

    brand = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    year = models.IntegerField()
    total_units = models.IntegerField()
    unavailable_units = models.IntegerField(default=0)
    car_type = models.CharField(max_length=20, choices=CAR_TYPES)
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2)
    daily_rate = models.DecimalField(max_digits=8, decimal_places=2)
    features = models.TextField()

    def __str__(self):
        return f"{self.brand} {self.model} ({self.year})"

    def get_reserved_total_units(self, start_datetime, end_datetime):
        """
        Calculate how many units of this car are reserved for a given period.
        Handles hourly bookings with precise time comparison.
        """
        from .models import Reservation

        # Ensure datetimes are timezone-aware
        if timezone.is_naive(start_datetime):
            start_datetime = timezone.make_aware(start_datetime)
        if timezone.is_naive(end_datetime):
            end_datetime = timezone.make_aware(end_datetime)

        # Get existing reservations
        existing_reservations = Reservation.objects.filter(
            car=self,
            status__in=['pending', 'partial', 'paid', 'active']
        )

        # Count only truly overlapping reservations
        overlapping_count = existing_reservations.filter(
            start_date__lt=end_datetime,
            end_date__gt=start_datetime
        ).exclude(
            models.Q(start_date=end_datetime) |  # Reservation starts exactly when requested period ends
            models.Q(end_date=start_datetime)    # Reservation ends exactly when requested period starts
        ).count()

        return overlapping_count


    @property
    def available_units(self):
        """Returns the number of units that are available"""
        return max(0, self.total_units - self.unavailable_units)

    def is_available(self, start_datetime, end_datetime):
        """
        Check if there are any available units of this car for the given period.
        """
        available = self.available_units
        if available <= 0:
            return False

        reserved_total = self.get_reserved_total_units(start_datetime, end_datetime)
        return (available - reserved_total) > 0

    def get_available_total_units(self, start_datetime, end_datetime):
        """
        Return the number of available units for the given period.
        """
        available = self.available_units
        if available <= 0:
            return 0

        reserved_total = self.get_reserved_total_units(start_datetime, end_datetime)
        return max(0, available - reserved_total)

    @property
    def is_currently_available(self):
        """
        Check if any units are available now.
        """
        if self.available_units <= 0:
            return False

        now = timezone.localtime(timezone.now())
        next_hour = now + timezone.timedelta(hours=1)
        return self.get_available_total_units(now, next_hour) > 0

    def get_main_image(self):
        return self.carimages_set.filter(is_main=True).first() or self.carimages_set.first()

    @property
    def weekly_rate(self):
        return self.daily_rate * 6


class CarImage(models.Model):
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='carimages_set')
    image = models.ImageField(upload_to='car_images/')
    is_main = models.BooleanField(default=False)
    caption = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return f"Image for {self.car.brand} {self.car.model}"

    class Meta:
        ordering = ['-is_main', 'id']


class Reservation(models.Model):
    RATE_TYPES = [
        ('hourly', 'Hourly'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('partial', 'Partial'),
        ('paid', 'Paid'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    car = models.ForeignKey(Car, on_delete=models.CASCADE)
    rate_type = models.CharField(max_length=10, choices=RATE_TYPES)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    receipt_image = models.ImageField(upload_to='receipts/', blank=True, null=True)
    reference_number = models.CharField(max_length=50, blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s reservation for {self.car.brand} {self.car.model}"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    license_image = models.ImageField(upload_to='licenses/', blank=True, null=True)
    license_number = models.CharField(max_length=50, blank=True, null=True)
    license_expiration = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"{self.user.username}'s profile"


class PasswordResetToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def __str__(self):
        return f"Password reset token for {self.user.username}"

    def is_valid(self):
        return timezone.localtime(timezone.now()) < self.expires_at
