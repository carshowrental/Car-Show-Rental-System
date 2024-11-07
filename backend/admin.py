from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from backend.models import *

# Modify the default UserAdmin
UserAdmin.list_display = ('username', 'email', 'is_staff', 'is_active', 'date_joined')
UserAdmin.fieldsets = (
    (None, {'fields': ('username', 'password')}),
    ('Personal info', {'fields': ('email',)}),
    ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
    ('Important dates', {'fields': ('last_login', 'date_joined')}),
)

# Your existing admin configurations
class CarImageInline(admin.TabularInline):
    model = CarImage
    extra = 3

class CarAdmin(admin.ModelAdmin):
    inlines = [CarImageInline]
    list_display = ('brand', 'model', 'year', 'daily_rate')
    list_filter = ('brand', 'car_type', 'year')
    search_fields = ('brand', 'model')

# Register all your models
admin.site.register(Car, CarAdmin)
admin.site.register(CarImage)
admin.site.register(Reservation)
admin.site.register(UserProfile)