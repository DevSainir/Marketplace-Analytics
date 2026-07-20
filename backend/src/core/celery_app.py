"""Celery application factory and configuration.

The worker shares the exact same :mod:`src.core.config` settings object as the
API, guaranteeing both processes speak to the same Redis broker and Postgres
instance. Task modules are autodiscovered from each business module's
``tasks`` submodule so domains own their own background jobs.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from src.core.config import settings
from src.core.logging import configure_logging

configure_logging()

celery_app: Celery = Celery(
    "marketplace",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Moscow",  # WB API operates in Moscow Time (UTC+3).
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
)

# Nightly refresh: because ``timezone`` is Europe/Moscow, this crontab fires at
# 06:00 MSK. It harvests yesterday's funnel + stock for every SKU and the last
# week of advertising for all active/paused campaigns.
celery_app.conf.beat_schedule = {
    "nightly-harvest-all": {
        "task": "monitoring.harvest_all",
        "schedule": crontab(hour=6, minute=0),
        "kwargs": {"days": 7},
    },
    # «Процент выкупа» inputs: re-read the order-date cohorts that are still
    # maturing (deliveries keep being accepted/refused for ~3 weeks). Runs an
    # hour after the harvest so it never competes with it for the same
    # rate-limited analytics surface, and stays out of harvest_all because it
    # is catalogue-wide and costs ~22 sequential requests per workspace.
    "nightly-refresh-buyout-cohorts": {
        "task": "monitoring.refresh_buyout_cohorts",
        "schedule": crontab(hour=7, minute=0),
    },
    # The matrix notes' running title: at the day boundary, each SKU's header
    # continues onto the new day as a real row (the comment does not — it is
    # per-day). 21:00 MSK is 00:00 in Bishkek, where the team works: that is the
    # moment their new day starts, so its column carries the title from the
    # first time anyone opens the table.
    "daily-carry-note-headers": {
        "task": "monitoring.carry_day_headers",
        "schedule": crontab(hour=21, minute=0),
    },
    # Housekeeping: auth.refresh_tokens gains a row per login/refresh forever;
    # purge rows long past expiry so the table stays bounded.
    "daily-purge-expired-refresh-tokens": {
        "task": "auth.purge_expired_refresh_tokens",
        "schedule": crontab(hour=4, minute=30),
    },
}

# Autodiscover ``tasks.py`` inside each registered business module.
celery_app.autodiscover_tasks(
    packages=[
        "src.modules.monitoring",
        "src.modules.users",
    ],
)
