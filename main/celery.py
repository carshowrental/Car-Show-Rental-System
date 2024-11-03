# celery_config.py (in your project directory)

import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'main.settings')

app = Celery('main')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Configure periodic tasks
app.conf.beat_schedule = {
    'cancel-pending-reservations': {
        'task': 'backend.tasks.cancel_pending_reservations',
        'schedule': crontab(minute='*/1'),  # Run every 1 minutes
    },
    'cancel-partial-payment-reservations': {
        'task': 'backend.tasks.cancel_partial_payment_reservations',
        'schedule': crontab(minute='*/1'),  # Run every 1 minutes
    },
    'update-reservation-statuses': {
        'task': 'backend.tasks.update_reservation_statuses',
        'schedule': crontab(minute='*/1'),  # Run every 1 minutes
    },
    'send-reservation-reminders': {
        'task': 'backend.tasks.send_reservation_reminders',
        'schedule': crontab(minute='*/1'),  # Run every 1 minutes
    },
}