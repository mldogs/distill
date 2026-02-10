"""Celery Beat schedule configuration."""

from celery.schedules import crontab

# Celery Beat schedule
# https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html
#
# Dynamic automation:
#   - Every minute: automation_tick checks DB settings (automation.*) and schedules
#     ingestion/novelty/daily v4 ranking when due.
#
# Daily tasks (00:XX):
#   :10 - rank weekly (v3)
#   :15 - rank weekly (v4)
#   :20 - rank monthly (v3)
#   :25 - rank monthly (v4)
#   03:00 - deep fetch (last 7 days)

CELERY_BEAT_SCHEDULE = {
# === Dynamic automation tick ===

    # Replace hardcoded intervals with DB-controlled settings (see core/settings.py).
    "automation-tick": {
        "task": "jobs.tasks.automation_tick",
        "schedule": crontab(minute="*"),  # Every minute
    },

    # === Daily tasks ===

    # Weekly ranking once a day
    "rank-weekly-v3": {
        "task": "jobs.tasks.rank_posts",
        "schedule": crontab(hour=0, minute=10),
        "kwargs": {
            "period": "weekly",
            "formula": "v3",
        },
    },

    # Weekly ranking v4
    "rank-weekly-v4": {
        "task": "jobs.tasks.rank_posts",
        "schedule": crontab(hour=0, minute=15),
        "kwargs": {
            "period": "weekly",
            "formula": "v4",
        },
    },

    # Monthly ranking v3
    "rank-monthly-v3": {
        "task": "jobs.tasks.rank_posts",
        "schedule": crontab(hour=0, minute=20),
        "kwargs": {
            "period": "monthly",
            "formula": "v3",
        },
    },

    # Monthly ranking v4
    "rank-monthly-v4": {
        "task": "jobs.tasks.rank_posts",
        "schedule": crontab(hour=0, minute=25),
        "kwargs": {
            "period": "monthly",
            "formula": "v4",
        },
    },

    # Deep fetch once a day (last 7 days)
    "deep-fetch-daily": {
        "task": "jobs.tasks.fetch_all_channels",
        "schedule": crontab(hour=3, minute=0),
        "kwargs": {
            "since_days": 7,
            "stagger_seconds": 1.0,
            "mode": "window",
        },
    },
}
