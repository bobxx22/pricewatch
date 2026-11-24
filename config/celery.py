"""Celery application. Settings are read from Django settings with the CELERY_ prefix."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("pricewatch")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
