from celery import shared_task
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.db import transaction
import requests
from .models import Reservation


class SMSService:
    """Handles all SMS-related operations using Teams SMS Program"""
    def __init__(self):
        self.api_secret = settings.TEAMS_SMS_API_SECRET
        self.device_id = settings.TEAMS_SMS_DEVICE_ID
        self.api_url = "https://sms.teamssprogram.com/api/send/sms"

    def send_sms(self, phone_number, message):
        """Send SMS with proper error handling"""
        if not phone_number:
            return False

        # Ensure phone number starts with +63
        if phone_number.startswith('0'):
            phone_number = '+63' + phone_number[1:]
        elif not phone_number.startswith('+63'):
            phone_number = '+63' + phone_number

        payload = {
            "secret": self.api_secret,
            "mode": "devices",
            "device": self.device_id,
            "sim": 1,
            "priority": 1,
            "phone": phone_number,
            "message": message
        }

        try:
            response = requests.post(self.api_url, params=payload, timeout=10)
            response.raise_for_status()
            result = response.json()

            if result.get('success'):
                return True
            else:
                return False
        except requests.RequestException as e:
            return False

@shared_task
def cancel_pending_reservations():
    """Cancel reservations that have been pending for more than 1 hour"""
    cutoff_time = timezone.localtime(timezone.now()) - timedelta(hours=1)
    sms_service = SMSService()

    try:
        with transaction.atomic():
            pending_reservations = Reservation.objects.select_related(
                'user__userprofile',
                'car'
            ).filter(
                status='pending',
                created_at__lt=cutoff_time
            )

            cancelled_count = 0
            for reservation in pending_reservations:
                reservation.status = 'cancelled'
                reservation.save()
                cancelled_count += 1

                message = (
                    f"Your reservation for {reservation.car.brand} {reservation.car.model} has been cancelled due to pending payment.\n\n"
                    f"- Car Show Car Rental Team"
                )
                sms_service.send_sms(reservation.user.userprofile.phone_number, message)

        return f"Cancelled {cancelled_count} reservations"
    except Exception as e:
        raise

@shared_task
def update_reservation_statuses():
    """Update reservation statuses based on time and payment status"""
    now = timezone.localtime(timezone.now())
    sms_service = SMSService()

    try:
        with transaction.atomic():
            # Update to active
            activated_count = Reservation.objects.select_related(
                'user__userprofile',
                'car'
            ).filter(
                status='paid',
                start_datetime__lte=now,
                end_datetime__gt=now
            ).update(status='active')

            # Update to completed
            completed_count = Reservation.objects.select_related(
                'user__userprofile',
                'car'
            ).filter(
                status='active',
                end_datetime__lte=now
            ).update(status='completed')

            # Send notifications for activated reservations
            for reservation in Reservation.objects.filter(status='active').select_related('user__userprofile', 'car'):
                message = (
                    f"Your reservation for {reservation.car.brand} {reservation.car.model} is now active.\n\n"
                    f"Enjoy your ride!\n\n"
                    f"- Car Show Car Rental Team"
                )
                sms_service.send_sms(reservation.user.userprofile.phone_number, message)

            # Send notifications for completed reservations
            for reservation in Reservation.objects.filter(status='completed').select_related('user__userprofile', 'car'):
                message = (
                    f"Your reservation for {reservation.car.brand} {reservation.car.model} has been completed.\n\n" 
                    f"Thank you for choosing our service!\n\n"
                    f"- Car Show Car Rental Team"
                )
                sms_service.send_sms(reservation.user.userprofile.phone_number, message)

        return f"Updated {activated_count} to active, {completed_count} to completed"
    except Exception as e:
        raise

@shared_task
def send_reservation_reminders():
    """Send SMS reminders for upcoming reservations"""
    now = timezone.localtime(timezone.now())
    one_day_from_now = now + timedelta(days=1)
    one_hour_from_now = now + timedelta(hours=1)
    sms_service = SMSService()

    try:
        # Send pickup reminders (1 day before)
        upcoming_reservations = Reservation.objects.select_related(
            'user__userprofile',
            'car'
        ).filter(
            status__in=['paid', 'partial'],
            start_datetime__date=one_day_from_now.date()
        )

        pickup_reminder_count = 0
        for reservation in upcoming_reservations:
            message = (
                f"REMINDER: Your car rental for {reservation.car.brand} {reservation.car.model} starts tomorrow at {reservation.start_datetime.strftime('%I:%M %p')}.\n\n"
                f"Please arrive on time for pickup.\n\n"
                f"- Car Show Car Rental Team"
            )
            if sms_service.send_sms(reservation.user.userprofile.phone_number, message):
                pickup_reminder_count += 1

        # Send return reminders (1 hour before end)
        ending_reservations = Reservation.objects.select_related(
            'user__userprofile',
            'car'
        ).filter(
            status='active',
            end_datetime__range=(one_hour_from_now, one_hour_from_now + timedelta(minutes=5))
        )

        return_reminder_count = 0
        for reservation in ending_reservations:
            message = (
                f"REMINDER: Your car rental for {reservation.car.brand} {reservation.car.model} ends in 1 hour at {reservation.end_datetime.strftime('%I:%M %p')}.\n\n"
                f"Please ensure timely return to avoid additional charges.\n\n"
                f"- Car Show Car Rental Team"
            )
            if sms_service.send_sms(reservation.user.userprofile.phone_number, message):
                return_reminder_count += 1

        return f"Sent {pickup_reminder_count} pickup and {return_reminder_count} return reminders"
    except Exception as e:
        raise