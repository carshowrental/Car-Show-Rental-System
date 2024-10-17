from django.db import models
from django.contrib.auth.models import User
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
    car_type = models.CharField(max_length=20, choices=CAR_TYPES)
    price_per_day = models.DecimalField(max_digits=8, decimal_places=2)
    features = models.TextField()

    def __str__(self):
        return f"{self.brand} {self.model} ({self.year})"

    def is_available(self, start_date, end_date):
        from .models import Reservation  # Import here to avoid circular import
        overlapping_reservations = Reservation.objects.filter(
            car=self,
            start_date__lte=end_date,
            end_date__gte=start_date,
            status__in=['pending', 'paid', 'active']
        )
        return not overlapping_reservations.exists()

    @property
    def is_currently_available(self):
        today = timezone.now().date()
        return self.is_available(today, today)

    def get_main_image(self):
        return self.carimages_set.filter(is_main=True).first() or self.carimages_set.first()

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
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    car = models.ForeignKey(Car, on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField()
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