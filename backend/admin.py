from django.contrib import admin
from backend.models import *

class CarImageInline(admin.TabularInline):
    model = CarImage
    extra = 3

class CarAdmin(admin.ModelAdmin):
    inlines = [CarImageInline]
    list_display = ('brand', 'model', 'year', 'price_per_day')
    list_filter = ('brand', 'car_type', 'year')
    search_fields = ('brand', 'model')

admin.site.register(Car, CarAdmin)
admin.site.register(CarImage)
admin.site.register(Reservation)
admin.site.register(UserProfile)
