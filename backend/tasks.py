import logging
from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Reservation

logger = logging.getLogger(__name__)


class SMSService:
    """Handles all SMS-related operations using Teams SMS Program"""

    def __init__(self):
        self.api_secret = settings.SEMAPHORE_API_KEY
        self.sender_name = settings.SEMAPHORE_SENDER_NAME
        self.api_url = "https://api.semaphore.co/api/v4/messages"

    def send_sms(self, phone_number, message):
        """Send SMS with proper error handling and logging"""
        if not phone_number:
            logger.warning("No phone number provided for SMS")
            return False

        # Ensure phone number starts with +63
        if phone_number.startswith('0'):
            phone_number = '+63' + phone_number[1:]
        elif not phone_number.startswith('+63'):
            phone_number = '+63' + phone_number

        payload = {
            'apikey': self.api_secret,
            'number': phone_number,
            'message': message,
            'sendername': self.sender_name
        }

        try:
            response = requests.post(self.api_url, json=payload)
            response.raise_for_status()
            result = response.json()

            if result.get('success'):
                logger.info(f"SMS sent successfully to {phone_number}")
                return True
            else:
                logger.error(f"SMS sending failed to {phone_number}: {result.get('message', 'Unknown error')}")
                return False
        except requests.RequestException as e:
            logger.error(f"SMS sending failed to {phone_number}: {str(e)}")
            return False


@shared_task
def cancel_pending_reservations():
    """Cancel reservations that have been pending for more than 1 hour"""
    now = timezone.localtime(timezone.now())  # Current time
    one_hour_ago = now - timedelta(hours=1)
    sms_service = SMSService()

    try:
        with transaction.atomic():
            # Get the pending reservations that need to be cancelled
            pending_reservations = Reservation.objects.select_related(
                'user__userprofile',
                'car'
            ).filter(
                status='pending',
                created_at__lt=one_hour_ago,
                start_datetime__gt=now
            )

            cancelled_count = 0
            for reservation in pending_reservations:
                # Update reservation status
                reservation.status = 'cancelled'
                reservation.save()
                cancelled_count += 1

                # Send cancellation message
                message = (
                    f"Your reservation for {reservation.car.brand} {reservation.car.model} has been cancelled due to pending payment.\n\n"
                    f"- Car Show Car Rental Team"
                )
                sms_service.send_sms(reservation.user.userprofile.phone_number, message)

        logger.info(f"Successfully cancelled {cancelled_count} pending reservations")
        return f"Cancelled {cancelled_count} reservations"
    except Exception as e:
        logger.error(f"Error in cancel_pending_reservations: {str(e)}")
        raise


@shared_task
def cancel_partial_payment_reservations():
    """Cancel reservations with partial payment status that have reached their start time"""
    now = timezone.localtime(timezone.now())
    sms_service = SMSService()

    try:
        with transaction.atomic():
            # Get partial payment reservations that have reached their start time
            partial_reservations = Reservation.objects.select_related(
                'user__userprofile',
                'car'
            ).filter(
                status='partial',
                start_datetime__lte=now
            )

            cancelled_count = 0
            for reservation in partial_reservations:
                # Update reservation status
                reservation.status = 'cancelled'
                reservation.save()
                cancelled_count += 1

                # Send cancellation message
                message = (
                    f"Your reservation for {reservation.car.brand} {reservation.car.model} has been cancelled due to incomplete payment.\n\n"
                    f"Please complete the full payment for future reservations.\n\n"
                    f"- Car Show Car Rental Team"
                )
                sms_service.send_sms(reservation.user.userprofile.phone_number, message)

        logger.info(f"Successfully cancelled {cancelled_count} partial payment reservations")
        return f"Cancelled {cancelled_count} partial payment reservations"
    except Exception as e:
        logger.error(f"Error in cancel_partial_payment_reservations: {str(e)}")
        raise


@shared_task
def update_reservation_statuses():
    """Update reservation statuses based on time and payment status"""
    now = timezone.localtime(timezone.now())
    sms_service = SMSService()

    try:
        with transaction.atomic():
            # Get reservations that need to be activated
            to_activate = Reservation.objects.select_related(
                'user__userprofile',
                'car'
            ).filter(
                status='paid',
                start_datetime__lte=now,
                end_datetime__gt=now
            )

            # Update and notify for activations
            activated_count = 0
            for reservation in to_activate:
                reservation.status = 'active'
                reservation.save()
                activated_count += 1

                message = (
                    f"Your reservation for {reservation.car.brand} {reservation.car.model} is now active.\n\n"
                    f"Enjoy your ride!\n\n"
                    f"- Car Show Car Rental Team"
                )
                sms_service.send_sms(reservation.user.userprofile.phone_number, message)

        logger.info(f"Updated statuses: {activated_count} activated")
        return f"Updated {activated_count} to active"
    except Exception as e:
        logger.error(f"Error in update_reservation_statuses: {str(e)}")
        raise


@shared_task
def send_reservation_reminders():
    """Send SMS reminders for upcoming reservations"""
    now = timezone.localtime(timezone.now())

    twenty_four_hours_window_start = now + timedelta(hours=23, minutes=59, seconds=30)
    twenty_four_hours_window_end = now + timedelta(hours=24, minutes=0, seconds=30)

    one_hour_window_start = now + timedelta(minutes=59, seconds=30)
    one_hour_window_end = now + timedelta(hours=1, seconds=30)

    sms_service = SMSService()

    try:
        with transaction.atomic():
            # Lock and fetch upcoming reservations
            upcoming_reservations = Reservation.objects.filter(
                status__in=['paid', 'partial'],
                start_datetime__gte=twenty_four_hours_window_start,
                start_datetime__lte=twenty_four_hours_window_end,
                pickup_reminder_sent=False
            ).select_for_update(skip_locked=True)

            # Lock and fetch ending reservations
            ending_reservations = Reservation.objects.filter(
                status='active',
                end_datetime__gte=one_hour_window_start,
                end_datetime__lte=one_hour_window_end,
                return_reminder_sent=False
            ).select_for_update(skip_locked=True)

            pickup_reminder_count = 0
            for reservation in upcoming_reservations:
                # Fetch related data separately
                user_profile = reservation.user.userprofile
                car = reservation.car

                # Convert to local time for display
                local_start_time = timezone.localtime(reservation.start_datetime)

                message = (
                    f"REMINDER: Your car rental for {car.brand} {car.model} starts tomorrow at {local_start_time.strftime('%I:%M %p')}.\n\n"
                    f"Please arrive on time for pickup.\n\n"
                    f"- Car Show Car Rental Team"
                )
                # Send pickup reminder message
                if sms_service.send_sms(user_profile.phone_number, message):
                    reservation.pickup_reminder_sent = True
                    reservation.save(update_fields=['pickup_reminder_sent'])
                    pickup_reminder_count += 1

            return_reminder_count = 0
            for reservation in ending_reservations:
                # Fetch related data separately
                user_profile = reservation.user.userprofile
                car = reservation.car

                # Convert to local time for display
                local_end_time = timezone.localtime(reservation.end_datetime)

                message = (
                    f"REMINDER: Your car rental for {car.brand} {car.model} ends in 1 hour at {local_end_time.strftime('%I:%M %p')}.\n\n"
                    f"Please ensure timely return to avoid additional charges.\n\n"
                    f"- Car Show Car Rental Team"
                )
                # Send return reminder message
                if sms_service.send_sms(user_profile.phone_number, message):
                    reservation.return_reminder_sent = True
                    reservation.save(update_fields=['return_reminder_sent'])
                    return_reminder_count += 1

        logger.info(f"Sent {pickup_reminder_count} pickup reminders and {return_reminder_count} return reminders")
        return f"Sent {pickup_reminder_count} pickup and {return_reminder_count} return reminders"
    except Exception as e:
        logger.error(f"Error in send_reservation_reminders: {str(e)}")
        raise
