"""Celery application configuration."""

import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

# Redis configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Create Celery app
celery_app = Celery(
    "jobs",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["jobs.tasks"],
)

# Celery configuration
celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Task settings
    task_track_started=True,
    task_time_limit=600,  # 10 minutes max per task
    task_soft_time_limit=540,  # Soft limit 9 minutes

    # Worker settings
    worker_prefetch_multiplier=1,  # Don't prefetch, better for rate limiting
    worker_concurrency=4,  # Default workers per process

    # Rate limiting - can be overridden per task
    task_default_rate_limit="20/s",

    # Retry settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # Result expiration
    result_expires=3600,  # 1 hour

    # Beat scheduler - use /tmp for Docker containers
    beat_schedule_filename="/tmp/celerybeat-schedule",
)

# Import beat schedule
celery_app.conf.beat_schedule = {}

# Load schedule from scheduler module when available
try:
    from jobs.scheduler import CELERY_BEAT_SCHEDULE
    celery_app.conf.beat_schedule = CELERY_BEAT_SCHEDULE
except ImportError:
    pass
