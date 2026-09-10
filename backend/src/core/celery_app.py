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
from src.core.observability.celery_runtime import prepare_multiprocess_dir

configure_logging()

# Ensures the multiprocess metrics directory exists before any prefork child
# needs it. It does NOT empty it — a tmpfs mount does that, and the difference
# is load-bearing: see `prepare_multiprocess_dir` for why wiping here would
# silently orphan the parent's counter files instead.
#
# Importing this module is also what REGISTERS the Celery signal handlers —
# task context, trace propagation, task metrics and the worker's own exporter.
# They are connected by decorator at import time, so the import is not
# incidental and must not be tidied away as unused.
prepare_multiprocess_dir()

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
    # Celery replaces the root logger's handlers on worker startup, which would
    # undo `configure_logging()` above and put the worker's lines back into
    # Celery's plain-text format — unparseable to a shipper, and exactly the
    # lines being read when a harvest failed. `src.core.observability`
    # `.celery_runtime` also connects to the `setup_logging` signal, which is
    # what stops the hijack rather than undoing it afterwards; this flag is the
    # declarative half of the same decision (register P2.2).
    worker_hijack_root_logger=False,
)

# Nightly refresh: because ``timezone`` is Europe/Moscow, this crontab fires at
# 06:00 MSK. It harvests yesterday's funnel + stock for every SKU and the last
# week of advertising for all active/paused campaigns.
celery_app.conf.beat_schedule = {
    # A/B photo rotations, after the harvest that writes the advertising rows
    # they read. 08:00 MSK leaves the 06:00 harvest and the 07:00 cohort pass
    # room to finish; a rotation that runs on a half-written day would
    # under-count the live photo and delay its swap by a day.
    # A/B photo rotations. Every five minutes, not nightly: WB's advertising
    # counters are cumulative and move within minutes, so the difference between
    # two reads is the traffic of the interval between them — which is what lets
    # a photo turn over several times a day. One fullstats call covers up to 50
    # campaigns, so the cost does not grow with the number of tests; at three
    # requests per minute allowed, this spends about 7% of the budget, and the
    # rest is shared with the harvest through the Redis bucket.
    "ab-tests-poll-rotations": {
        "task": "ab_tests.poll_rotations",
        "schedule": crontab(minute="*/5"),
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
    # finds an unharvested report pays for the walk, and harvest_all_workspaces
    # holds a Redis lock so the next tick cannot start a second copy alongside
    # it.
    #
    # What a tick may spend is set by WB, not by us: `reportDetailByPeriod`
    # serves ONE request per ~15 minutes per seller token (measured 2026-09-07,
    # `x-ratelimit-reset: 917`). An hourly tick's probe is one of the four
    # tokens that hour, and a tick that harvests spends one more per week it
    # walks — see src/modules/finreports/tasks/settlement.py, which is why the
    # walk covers a week per request and no longer re-reads a rolling 28 days
    # it already holds.
    #
    # harvest and cohort refresh own those hours, and the walk competes with
    # them for the same rate-limited analytics surfaces.
    "hourly-finreports-harvest": {
        "task": "finreports.harvest_finance",
        # 03:00 belongs to the reconciliation pass below. Both take the same
        # lock, so leaving the hour in would make the two race for it and the
        # loser return `skipped_locked` — and the loser would sometimes be the
        # pass that only gets one chance a day.
        "schedule": crontab(hour="0-2,4,8-23", minute=0),
        "kwargs": {"days": 28},
    },
    # The hourly tick can only ever look FORWARD: its span starts at the
    # settlement watermark, and the watermark jumps to the newest report's
    # stated end. WB does not publish in that order — it forms single-day
    # supplementary reports and starts serving their rows days later — so a
    # report covering days behind that jump is unreachable for good. On
    # 2026-08-31 that cost every workspace a day of settlement, and nothing in
    # the product could tell: the counters moved, the task succeeded, the P&L
    # was simply short a day.
    #
    # 03:00 MSK, and the hourly tick gives up that hour above. Not 05:00-07:00:
    # refresh, and this pass competes for the same rate-limited surfaces. It is
    # also the most expensive pass we run — two or three extra requests per
    # workspace, each a quarter of an hour apart — so it takes an hour when
    # nothing is published and the hourly tick would have found nothing anyway.
    "daily-finreports-reconcile": {
        "task": "finreports.harvest_finance",
        "schedule": crontab(hour=3, minute=0),
        "kwargs": {"days": 28, "reconcile": True},
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
