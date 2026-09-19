"""Celery metrics — the half of this service with no user watching it.

Queue depth, task outcomes, runtime, and the two memory readings that decide
whether a worker child is recycled cleanly or killed by the kernel.
"""

from __future__ import annotations

from typing import Final

from prometheus_client import Counter, Gauge, Histogram

# --------------------------------------------------------------------------- #
# Celery — the half of this service with no user watching it.
# --------------------------------------------------------------------------- #

#: Messages waiting in a queue, sampled at scrape time by reading Redis
#: directly (see `collectors.py`). Not incremented by anything: a queue's
#: length is a fact about Redis, and deriving it from enqueue/dequeue counters
#: is how a metric drifts from reality after one lost message.
#:
#: `livemostrecent` for the same reason as the WB budget — every process that
#: samples it reads the same Redis key, so summing would multiply one queue by
#: the number of workers.
CELERY_QUEUE_LENGTH: Final[Gauge] = Gauge(
    "celery_queue_length",
    "Messages waiting in a Celery queue.",
    ["queue_name"],
    multiprocess_mode="livemostrecent",
)

#: Task outcomes. `state` is one of `success`, `failure`, `retry`, `revoked`,
#: `soft_timeout` — a closed set from Celery's own signals.
CELERY_TASKS: Final[Counter] = Counter(
    "celery_tasks_total",
    "Celery task executions by name and final state.",
    ["task_name", "state"],
)

#: End-to-end task runtime. The top bucket is 3600s because that is the soft
#: time limit (`src.core.celery_app`), so the last bucket boundary is exactly
#: the line a task is killed for crossing — which makes "approaching the limit"
#: a thing the histogram can actually show.
CELERY_TASK_DURATION: Final[Histogram] = Histogram(
    "celery_task_duration_seconds",
    "Wall-clock duration of one Celery task execution.",
    ["task_name"],
    buckets=(0.5, 1.0, 5.0, 15.0, 60.0, 300.0, 900.0, 1800.0, 3600.0),
)

#: Tasks whose prefork child died mid-run — in practice, the cgroup OOM killer.
#:
#: Counted apart from `celery_tasks_total{state="failure"}` because the two
#: differ in what they mean and in what an alert on them may say. An ordinary
#: failure is a task that ran and raised; this is a task that did not finish and
#: will not be retried — `acks_on_failure_or_timeout` acknowledges the message on
#: the way past, so nothing redelivers it (verified in Celery's
#: `Request.on_failure`, and on prod 2026-09-17, where the 01:00 finance harvest
#: died on its first workspace and the remaining four simply waited for the
#: 05:00 tick).
#:
#: It also cannot be reached through the failure RATE. Three of these in twelve
#: hours is 0.00007/s against a `TaskFailureRate` threshold of 0.05 — the shape
#: that alert is built for, a task failing over and over, is the opposite of
#: this one, which is rare and matters every single time.
CELERY_WORKER_LOST: Final[Counter] = Counter(
    "celery_worker_lost_total",
    "Tasks abandoned because the worker process running them died.",
    ["task_name"],
)

#: Buckets for the two memory histograms below, in bytes. Chosen around the
#: numbers that actually decide something rather than by a round progression:
#: 150 MB is a freshly forked child, 300 MB is `--max-memory-per-child`, 525 MB
#: is the high-water one child reached on prod on 2026-09-17, and 768 MB is the
#: cgroup cap the kernel enforces.
_MEMORY_BUCKETS: Final[tuple[float, ...]] = (
    128 * 1024 * 1024,
    160 * 1024 * 1024,
    200 * 1024 * 1024,
    250 * 1024 * 1024,
    300 * 1024 * 1024,
    375 * 1024 * 1024,
    450 * 1024 * 1024,
    525 * 1024 * 1024,
    640 * 1024 * 1024,
    768 * 1024 * 1024,
)

#: The child's high-water RSS when a task finished, by task.
#:
#: **This is the number `--max-memory-per-child` compares**, read from the same
#: `billiard.compat.mem_rss` the recycler reads, so the two cannot disagree
#: about what a child weighs. Its distribution is what the limit should be
#: chosen from — the current 300 MB was picked from three data points and an
#: argument, which is a guess wearing a number.
#:
#: Read it knowing what a high-water mark is: it never falls, and a freshly
#: forked child starts at the parent's resident set (~148 MB measured), because
#: copy-on-write pages count in both. So this says "what the child weighed when
#: this task ended", not "what this task needed" — for which see the growth
#: histogram below.
CELERY_TASK_PEAK_MEMORY: Final[Histogram] = Histogram(
    "celery_task_peak_memory_bytes",
    "Worker child's high-water resident set at the end of one task.",
    ["task_name"],
    buckets=_MEMORY_BUCKETS,
)

#: The child's high-water RSS when a task STARTED, by task.
#:
#: The one memory reading a task that dies still leaves behind, and the gap that
#: cost a day to notice. The two histograms above are written at
#: ``task_postrun``, so the twenty-one harvests the kernel killed on 09-18
#: recorded nothing at all — the surviving runs put `harvest_finance` at 369 MB
#: of growth while the cgroup gauge was touching 767 MB, and only the second
#: number was true.
#:
#: Recorded at ``task_prerun``, so it is written before anything can go wrong.
#: It does not say what the task then needed — nothing in this process can, once
#: the process is gone — but it says what it was given: the floor already spent
#: when it began. Paired with ``celery_worker_lost_total``, which names the task
#: from the PARENT and therefore survives, that is enough to tell "this task
#: wants too much" from "this task was handed too little", which is the question
#: the whole 09-18 diagnosis turned on.
#:
#: A histogram rather than a gauge on purpose: a gauge belonging to a child that
#: has died is retired by `mark_process_dead`, which would delete the evidence
#: at exactly the moment it became interesting. Histogram files outlive their
#: process, because their counts have to.
CELERY_TASK_START_MEMORY: Final[Histogram] = Histogram(
    "celery_task_start_memory_bytes",
    "Worker child's high-water resident set when a task began.",
    ["task_name"],
    buckets=_MEMORY_BUCKETS,
)

#: How much a task RAISED that high-water mark, by task.
#:
#: The attribution half, and the reason both exist. A high-water mark is
#: inherited: a cheap task that happens to run after an expensive one reports
#: the expensive one's number, so the histogram above would blame whichever task
#: ran next. This one is the difference across the task, which is zero for every
#: run that stayed under the line already reached — and the tasks whose
#: distribution is NOT mostly zero are the ones that decide the ceiling.
CELERY_TASK_MEMORY_GROWTH: Final[Histogram] = Histogram(
    "celery_task_memory_growth_bytes",
    "Bytes one task added to its worker child's high-water resident set.",
    ["task_name"],
    buckets=(0.0, *_MEMORY_BUCKETS[:-3]),
)
