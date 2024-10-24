import uuid

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Car(models.Model):
    CAR_TYPES = [
        ('sedan', 'Sedan'),
        ('suv', 'SUV'),
        ('sports', 'Sports Car'),
        ('van', 'Van'),
    ]

    brand = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    year = models.IntegerField()
    quantity = models.IntegerField()
    car_type = models.CharField(max_length=20, choices=CAR_TYPES)
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2)
    daily_rate = models.DecimalField(max_digits=8, decimal_places=2)
    features = models.TextField()

    def __str__(self):
        return f"{self.brand} {self.model} ({self.year})"

    def get_reserved_quantity(self, start_datetime, end_datetime):
        """
        Calculate how many units of this car are reserved for a given period.
        Works with both datetime and date objects, handling hourly, daily, and weekly rentals.
        The end time is exclusive, meaning a car can be booked starting exactly when another rental ends.
        """
        from .models import Reservation  # Import here to avoid circular import

        # Ensure we're working with datetime objects
        if not isinstance(start_datetime, timezone.datetime):
            start_datetime = timezone.make_aware(timezone.datetime.combine(start_datetime, timezone.datetime.min.time()))
        if not isinstance(end_datetime, timezone.datetime):
            end_datetime = timezone.make_aware(timezone.datetime.combine(end_datetime, timezone.datetime.min.time()))

        overlapping_reservations = Reservation.objects.filter(
            car=self,
            start_date__lt=end_datetime,  # Reservation starts before the new end time
            end_date__gt=start_datetime,  # Reservation ends after the new start time
            status__in=['pending', 'paid', 'active']
        )
        return overlapping_reservations.count()

    def is_available(self, start_datetime, end_datetime):
        """
        Check if there are any available units of this car for the given period.
        """
        reserved_quantity = self.get_reserved_quantity(start_datetime, end_datetime)
        return reserved_quantity < self.quantity

    def available_quantity(self, start_datetime, end_datetime):
        """
        Return the number of available units for the given period.
        """
        reserved_quantity = self.get_reserved_quantity(start_datetime, end_datetime)
        return max(0, self.quantity - reserved_quantity)

    @property
    def is_currently_available(self):
        """
        Check if any units are available now.
        """
        now = timezone.localtime(timezone.now())
        next_hour = now + timezone.timedelta(hours=1)
        return self.available_quantity(now, next_hour) > 0

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
        ('paid', 'Paid'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    car = models.ForeignKey(Car, on_delete=models.CASCADE)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    rate_type = models.CharField(max_length=10, choices=RATE_TYPES)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    payment_source_id = models.CharField(max_length=255, blank=True, null=True)
    payment_id = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    cancellation_notified = models.BooleanField(default=False)

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
