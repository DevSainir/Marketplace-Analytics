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

#: Backstop against a task that never returns. Not a performance budget — a
#: bound on how long one hung run may hold a worker slot, of which there are
#: four (``--concurrency=4``): without it, four stuck tasks are a permanently
#: blocked queue and no scheduled work runs again until someone notices.
#:
#: Sized from what production actually takes, measured over 72 h on
#: 2026-08-29 — the longest legitimate task by a wide margin is
#: ``monitoring.refresh_buyout_cohorts`` at ~1 610 s (27 min); the nightly
#: ``monitoring.harvest_all`` is ~63 s. An hour leaves that longest job better
#: than 2x headroom to grow into as tenants are added, and still turns "forever"
#: into "an hour".
_TASK_SOFT_TIME_LIMIT_SECONDS: int = 60 * 60

#: The hard kill, five minutes after the soft one. The SOFT limit is the control
#: that is meant to fire: it raises ``SoftTimeLimitExceeded`` *inside* the task,
#: so the run unwinds, releases its Redis lock and its DB connection, and is
#: acknowledged as failed. The hard limit SIGKILLs the worker process, and with
#: ``task_acks_late`` the message is then redelivered — a task that reliably
#: overran would loop forever. So the gap exists to give the soft limit time to
#: work, and the hard one only catches a task wedged somewhere that cannot raise
#: (a C-level call, an uninterruptible syscall).
#:
#: This is safe only because no task here autoretries on bare ``Exception``:
#: both modules' ``_TASK_RETRY_KWARGS`` name ``(IntegrationError,
#: OperationalError)``, neither of which ``SoftTimeLimitExceeded`` is.
_TASK_TIME_LIMIT_SECONDS: int = _TASK_SOFT_TIME_LIMIT_SECONDS + 300

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
    task_soft_time_limit=_TASK_SOFT_TIME_LIMIT_SECONDS,
    task_time_limit=_TASK_TIME_LIMIT_SECONDS,
)

# Nightly refresh: because ``timezone`` is Europe/Moscow, this crontab fires at
# 06:00 MSK. It harvests yesterday's funnel + stock for every SKU and the last
# week of advertising for all active/paused campaigns.
celery_app.conf.beat_schedule = {
    # A/B photo rotations, after the harvest that writes the advertising rows
    # they read. 08:00 MSK leaves the 06:00 harvest and the 07:00 cohort pass
    # room to finish; a rotation that runs on a half-written day would
    # under-count the live photo and delay its swap by a day.
    "ab-tests-advance-rotations": {
        "task": "ab_tests.advance_rotations",
        "schedule": crontab(hour=8, minute=0),
    },
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
    # history, so the series is ours to accumulate). 05:00 MSK, before the
    # finance harvest so each settlement row can price against a same-day tariff.
    "daily-finreports-snapshot-tariffs": {
        "schedule": crontab(hour=5, minute=0),
    },
    #
    # Hourly, not daily. WB publishes the weekly realization report on no fixed
    # day *and no fixed hour*: report 978271922 (03.08-09.08.2026) was formed on
    # 10.08 after that day's 08:00 run had already asked and been told there was
    # nothing, so the P&L showed an empty week for a full day until the next
    # run. One check a day means up to 24h of staleness every time WB publishes
    # during working hours.
    #
    # Ticking hourly is affordable only because of the freshness gate
    # (src/modules/finreports/tasks/freshness.py): a tick with nothing new costs
    # one `limit=1` request per workspace and stops there. Only a tick that
    # finds an unharvested report pays for the walk — minutes of paced
    # the next tick cannot start a second copy alongside it. The rolling 28-day
    # window keeps recent reports fresh and is upsert-idempotent, so re-running
    # is always safe.
    #
    # harvest and cohort refresh own those hours, and the walk competes with
    # them for the same rate-limited analytics surfaces.
    "hourly-finreports-harvest": {
        "task": "finreports.harvest_finance",
        "schedule": crontab(hour="0-4,8-23", minute=0),
        "kwargs": {"days": 28},
    },
}

# Autodiscover ``tasks.py`` inside each registered business module.
celery_app.autodiscover_tasks(
    packages=[
        "src.modules.monitoring",
        "src.modules.users",
        "src.modules.finreports",
        "src.modules.ab_tests",
    ],
)
