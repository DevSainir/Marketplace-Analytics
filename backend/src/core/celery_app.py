"""Celery application factory and configuration.

The worker shares the exact same :mod:`src.core.config` settings object as the
API, guaranteeing both processes speak to the same Redis broker and Postgres
instance. Task modules are autodiscovered from each business module's
``tasks`` submodule so domains own their own background jobs.
"""

from __future__ import annotations

import logging

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready

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

# Every time below is Moscow time (``timezone`` above).
#
# The working day starts at 07:00 MSK, and nightly work must be FINISHED by
# 06:30 — half an hour clear. Until 2026-09-28 the monitoring harvest ran
# 06:00-06:10 and the buyout-cohort pass 07:00-07:34, i.e. into the working day.
# The night now runs:
#
#   00:00 01:00 02:00  finance tick (yesterday's daily report)   ≤ 6 min
#   02:20              reference capture                          ≤ 1 min
#   03:00              database backup (host cron, not beat)      ≤ 40 min
#   04:00              finance reconciliation + summary warm-up   ≤ 23 min
#   04:30              refresh-token purge                        instant
#   05:05              monitoring harvest                         ≤ 10 min
#   05:20              buyout cohorts (after the harvest's rows)  ≤ 35 min → 05:55
#
# which leaves 35 minutes before the deadline for the harvest and the cohort pass
# to grow into; both walk every workspace in turn, at roughly one and a half
# and six minutes per workspace, so that is about five more workspaces.
#
# 03:00-03:40 belongs to the backup (`scripts/backup/cron/marketplace-backup`)
# and nothing here writes during it. On 2026-09-29 the reconciliation shared
# that minute with pg_dump, the postgres container hit its 384 MiB limit, the
# kernel killed a backend mid-COMMIT and the dump died with it. The
# reconciliation took hour 04 from the finance tick instead — it walks every new
# report the tick would have, and more.
#
# ``tests/unit/core/test_nightly_work_ends_before_the_workday.py`` holds every
# nightly entry to 06:30 at its measured worst-case runtime, and clear of the
# backup.
celery_app.conf.beat_schedule = {
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
    # Yesterday's funnel + stock for every SKU, today's price snapshot and the
    # last week of advertising for all active/paused campaigns. It re-reads the
    # last seven days every night, so a late WB revision of yesterday lands the
    # following night.
    "nightly-harvest-all": {
        "task": "monitoring.harvest_all",
        "schedule": crontab(hour=5, minute=5),
        "kwargs": {"days": 7},
    },
    # «Процент выкупа» inputs: re-read the order-date cohorts that are still
    # maturing (deliveries keep being accepted/refused for ~3 weeks). After the
    # harvest has finished, because it only UPDATEs funnel rows the harvest
    # inserted, and so it never competes with it for the analytics surface. It
    # stays out of harvest_all because it is catalogue-wide and costs ~22
    # sequential requests per workspace — the longest nightly job, ~35 minutes.
    "nightly-refresh-buyout-cohorts": {
        "task": "monitoring.refresh_buyout_cohorts",
        "schedule": crontab(hour=5, minute=20),
    },
    # The other half of the price snapshot. The customer price comes from the
    # order feed, which answers for a SKU only once it has sold *today*, so the
    # 05:05 harvest prices a fraction of the catalogue and the rest of the day's
    # sales land after it. This pass asks once more for the gaps only.
    #
    # 23:30 MSK, and the half hour is load-bearing in both directions: late
    # enough that almost the whole day has sold, early enough to finish before
    # the feed rolls over — a day is only fillable while it is still today.
    # Minute 30 keeps it off the hourly finreports tick at minute 0.
    "evening-top-up-customer-prices": {
        "task": "monitoring.top_up_customer_prices",
        "schedule": crontab(hour=23, minute=30),
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
    # history, so the series is ours to accumulate). 05:00 MSK, clear of the
    # 04:00 finance tick and before the monitoring harvest.
    "daily-finreports-snapshot-tariffs": {
        "schedule": crontab(hour=5, minute=0),
    },
    #
    # Scheduled on the hours a report can ARRIVE, and gated: each tick first
    # asks our own tables whether a seller is still owed anything today
    # (`finreports.tasks.harvest.due`) and spends WB requests only on those who
    # are. What a day brings is known in advance — the daily report for
    # yesterday, served in the small hours (01:01, 03:06, 04:01 on «Демо»,
    # 09.2026), and a weekly report only the day after a Sunday or a month end
    # (142 of 142), served from about 10:00 (10:03, 10:04, 12:54, latest 18:30).
    #
    # It was 58 ungated ticks a day, two `list` requests per seller each, to
    # find two or three reports. A report WB serves off-calendar — back-dated,
    # days late — is the 04:00 reconciliation's, which walks every seller
    # ungated; «Обновить» and a new workspace's first harvest are never gated.
    #
    # `harvest_all_workspaces` holds a Redis lock, so two entries firing in the
    # same minute run once. 03:00 belongs to the backup, 04:00 to the
    # reconciliation, and
    # refresh, which compete for the same rate-limited surfaces. The by-day tick
    # is daytime work on purpose: it exists for reports WB serves during the day.
    "finreports-harvest-at-night": {
        "task": "finreports.harvest_finance",
        # Yesterday's daily report; the 04:00 reconciliation asks again.
        "schedule": crontab(hour="0-2", minute=0),
        "kwargs": {"gated": True},
    },
    "finreports-harvest-by-day": {
        "task": "finreports.harvest_finance",
        # Whatever the night did not bring, and a weekly report served late.
        "schedule": crontab(hour="7-18", minute=0),
        "kwargs": {"gated": True},
    },
    # The two days a weekly report is formed, every quarter of an hour: WB shows
    # it on its own site the moment it is served, and an hour's lag on the one
    # document a seller waits for is what the tighter cadence buys off.
    "finreports-harvest-after-a-sunday": {
        "task": "finreports.harvest_finance",
        "schedule": crontab(day_of_week="mon", hour="8-18", minute="15,30,45"),
        "kwargs": {"gated": True},
    },
    "finreports-harvest-after-a-month-end": {
        "task": "finreports.harvest_finance",
        "schedule": crontab(day_of_month="1", hour="8-18", minute="15,30,45"),
        "kwargs": {"gated": True},
    },
    # The harvest tick can only ever look FORWARD: its span starts at the
    # settlement watermark, and the watermark jumps to the newest report's
    # stated end. WB does not publish in that order — it forms single-day
    # supplementary reports and starts serving their rows days later — so a
    # report covering days behind that jump is unreachable for good. On
    # 2026-08-31 that cost every workspace a day of settlement, and nothing in
    # the product could tell: the counters moved, the task succeeded, the P&L
    # was simply short a day.
    #
    # 04:00 MSK, and the night tick gives up that hour above. Not 03:00: that
    # is the backup's (see the table at the top). Not 05:00-05:55:
    # refresh, and this pass competes for the same rate-limited surfaces. Since
    # 2026-09-26 it covers every seller, not one in rotation: per seller it is
    # one list over the whole history (WB's totals for the archive) plus the
    # fortnight's re-walk and any archive report short of WB's total, a minute
    # apart, three sellers at a time.
    "daily-finreports-reconcile": {
        "task": "finreports.harvest_finance",
        "schedule": crontab(hour=4, minute=0),
        "kwargs": {"reconcile": True},
    },
    # The measurement the provisional daily tail owes: whether WB revises a daily
    # report after first serving it. Unknown — re-reading one 42 minutes later
    # found it identical, which rules out minute-by-minute top-ups and nothing
    # else — and until it is answered no day in the tail may be presented as
    # settled.
    #
    # The tail itself has no entry here: it runs inside the harvest tick above,
    # after each seller's weekly walk, because both lanes spend the same
    # one-request-a-minute Finance buckets and as separate schedules the loser of
    # an overlap simply skipped. This pass is separate because it is not part of
    # fetching — one list request per workspace screens every queued report, and
    # only a report whose totals moved costs a re-read.
    #
    # 12:40 MSK: outside the 05:00-05:55 block that belongs to the tariff
    # snapshot and the monitoring harvest, and clear of the 04:00 reconciliation.
    "daily-finreports-verify-daily-tail": {
        "task": "finreports.verify_daily_tail",
        "schedule": crontab(hour=12, minute=40),
    },
    # The history backfill's watchdog. Every lane is a chain of self-enqueueing
    # ticks, and a tick that dies before its re-enqueue ends the whole walk with
    # nothing scheduled to notice — which is exactly how NEVA's P&L lane spent
    # eleven hours doing nothing on 2026-09-10. This is the second thread of
    # continuation; see `src.modules.workspaces.tasks`.
    #
    # Every fifteen minutes rather than hourly because the cost is one indexed
    # read of a table with a handful of rows. It was sized when the lane moved
    # at one page per fifteen minutes; on finance-api a page is a minute, so a
    # dead lane now loses more per sweep interval, not less, and a slower sweep
    # would only make that worse.
    "backfill-watchdog": {
        "task": "workspaces.sweep_stalled_backfills",
        "schedule": crontab(minute="*/15"),
    },
    # The review history: each card group's rating and every review's state, so a
    # rating change can be explained after the fact (monitoring/models/reviews.py).
    # Earns nothing on the day, so it takes an hour nothing else wants: 19:40 MSK
    # is after the last daytime finance tick (18:00, 18:45 on a weekly-report
    # day), well clear of the 05:00-05:55 block and the 23:30 price top-up, and
    # the 21:00 header carry is a single UPDATE. Minute 40 keeps it off any
    # minute-0 tick. A large workspace's walk is ~150 paced pages, a few minutes;
    # the storefront reads are one card group every three seconds across the fleet.
    # It steps aside for a first-run harvest (see the task).
    "evening-snapshot-reviews": {
        "task": "monitoring.snapshot_reviews",
        "schedule": crontab(hour=19, minute=40),
    },
    # ---- the reference capture (`guide`) --------------------------------
    #
    # These two earn nothing. They exist because WB deletes several feeds on
    # a schedule and a day nobody captured is a day nobody can capture. So the
    # only real constraint on their timing is that they must never be the reason
    # a paying harvest waited for a worker slot.
    #
    # The window 00:00-03:00 is the quietest one this schedule has: the hourly
    # finance tick fires at minute 0 and finds nothing new on most of those
    # hours, and the nightly passes (backup 03:00, reconcile 04:00, tariffs
    # 05:00, harvest 05:05, cohorts 05:20) are all later. Each entry sits away from minute 0
    # for the same reason. The service layer also holds ONE lock across both, so
    # an overrun makes the next cadence a no-op rather than a second concurrent
    # walk.
    #
    # Cadence per source, and the measurement behind it, is in
    # `src.modules.guide.sources` — the rule is daily when a missed day is a
    # lost day and monthly otherwise.
    "guide-capture-daily": {
        "task": "guide.capture_daily",
        "schedule": crontab(hour=2, minute=20),
    },
    # First of the month, and the earlier of the two: this is the one that walks
    # windows of history, so it is the one most likely to run long.
    "guide-capture-monthly": {
        "task": "guide.capture_monthly",
        "schedule": crontab(hour=1, minute=30, day_of_month="1"),
    },
}

# Autodiscover ``tasks.py`` inside each registered business module.
celery_app.autodiscover_tasks(
    packages=[
        "src.modules.monitoring",
        "src.modules.users",
        "src.modules.finreports",
        "src.modules.ab_tests",
        "src.modules.workspaces",
        "src.modules.guide",
    ],
)


def _startup_logger() -> logging.Logger:
    """A plain stdlib logger: structlog may not be configured this early."""
    return logging.getLogger(__name__)


@worker_ready.connect  # type: ignore[untyped-decorator]
def _warm_settlement_rollups(**_: object) -> None:
    """Rebuild the P&L rollup a deploy's migration may just have cleared.

    A migration clears it whenever a money rule changes, and every deploy runs
    migrations and then starts this worker — so this is the first moment
    anything can rebuild it. Otherwise the first seller to open «Вся история»
    after such a deploy pays a rebuild the browser gives up on. Sent by name
    for the same reason as the sweep below; failure is swallowed because the
    rollup repairs itself on read anyway.
    """
    try:
        celery_app.send_task("finreports.warm_settlement_rollups")
    except Exception:
        _startup_logger().warning(
            "Could not enqueue the rollup warm-up at worker start; the first read "
            "will rebuild it instead.",
            exc_info=True,
        )


@worker_ready.connect  # type: ignore[untyped-decorator]
def _resume_orphaned_backfills(**_: object) -> None:
    """Adopt any history backfill this worker's predecessor was killed mid-tick.

    A backfill lane is a chain: one bounded tick, then it enqueues the next. A
    deploy recreates this container, and whatever tick was in flight dies before
    reaching that enqueue — so the chain ends, silently, every single time we
    ship. Without this the only recovery is the stalled-lane watchdog, which by
    design waits forty-five minutes before believing a lane is dead. Three
    deploys in a morning then cost a seller two hours of history arriving.

    A worker that has just started is running nothing, so a lane still claiming
    RUNNING is not a guess about staleness — it is an orphan, and can be
    restarted at once. It resumes from the cursor in its own row, so the worst
    case if one somehow WAS alive is a duplicate page against an idempotent
    upsert.

    Addressed by name and sent, never called: this module is imported by the API
    too, and importing a module's tasks from here would close the same cycle the
    whole `contract.py` arrangement exists to avoid. Failure is swallowed
    because a broker that is not ready in the first second of worker startup
    must not crash the worker — the watchdog is still behind this, just slower.
    """
    try:
        celery_app.send_task("workspaces.sweep_stalled_backfills", kwargs={"orphaned": True})
    except Exception:
        _startup_logger().warning(
            "Could not enqueue the orphaned-backfill sweep at worker start; "
            "the scheduled watchdog will pick any dead lane up within the hour.",
            exc_info=True,
        )
