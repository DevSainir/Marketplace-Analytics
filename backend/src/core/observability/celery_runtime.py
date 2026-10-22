"""Making the worker observable: context, metrics and an exporter of its own.

The API half of this service was already legible — every request binds a
context and emits a line. The worker half was not, and it is
the half that runs unattended: a failed request is answered with a 500 that
somebody sees, a failed nightly harvest is a number that is quietly stale until a
customer asks. This module closes that asymmetry.

Four things happen here, all through Celery's signals so that no task body has
to know about any of them.

**Context.** Every task binds ``task_id`` and ``task_name`` for the duration of
its run and clears them afterwards. A worker reuses its process across tasks,
so a context left bound attributes the next task's lines to the previous task's
tenant — confidently wrong evidence, which is worse than none
(:func:`src.core.tasks.run_task` already resets for exactly this reason; the
``task_postrun`` hook here is the belt to its braces, because a task that dies
before ``run_task`` returns never reaches it).

**Trace propagation.** A request that enqueues a harvest puts its ``trace_id``
in the Celery message headers, and the worker binds the same value minutes
later in another container. One search then returns the click and the work it
caused, which is the question every "why is my number wrong" conversation
turns into.

**An exporter.** The worker is not an ASGI app, so it serves its own metrics on
a port of its own — inside the Docker network, never published to the host.

**Multiprocess aggregation, which is why that exporter is not trivial.** The
prefork pool means the process answering a scrape is not the process that
counted the harvest. ``prometheus_client``'s multiprocess mode puts the
counters in mmap files under ``PROMETHEUS_MULTIPROC_DIR`` so that any of them
can read all of them. Two consequences are easy to get wrong and are handled
below: the directory must be **empty at worker start** (files from a previous
container would be summed into this one's totals, so a restart would look like
a traffic spike — solved by mounting it as a tmpfs rather than by wiping it,
for the reason spelled out in :func:`prepare_multiprocess_dir`), and a child
that exits must be **marked dead** (or its last gauge values are counted
forever as though the process were still live).
"""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path
from typing import Any, NamedTuple

from billiard.compat import mem_rss
from celery.exceptions import WorkerLostError
from celery.signals import (
    before_task_publish,
    celeryd_init,
    setup_logging,
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    worker_process_shutdown,
    worker_ready,
)
from prometheus_client import CollectorRegistry, multiprocess, start_http_server

from src.core.config import settings
from src.core.logcontext import bind_task, current_trace_id, reset_context
from src.core.logging import adopt_celery_loggers, configure_logging, get_logger
from src.core.observability.metrics import (
    CELERY_TASK_DURATION,
    CELERY_TASK_MEMORY_GROWTH,
    CELERY_TASK_PEAK_MEMORY,
    CELERY_TASK_START_MEMORY,
    CELERY_TASKS,
    CELERY_WORKER_LOST,
    set_app_info,
)
from src.core.observability.sentry import configure_sentry

logger = get_logger(__name__)

#: Message header carrying the enqueuing request's trace id.
#:
#: Two constraints picked this name. It must not collide with one of Celery's
#: own protocol-2 header names (``id``, ``task``, ``root_id``, ``origin``,
#: ``retries`` and friends), which are unprefixed and would silently win — so
#: it is namespaced. And it must be a valid Python identifier, because the
#: worker reads it back off ``task.request``, where a hyphenated name is
#: reachable only through ``get()`` and not as an attribute.
TRACE_HEADER = "marketplace_trace_id"


class _TaskStart(NamedTuple):
    """What a task's beginning has to record for its end to mean anything.

    Attributes:
        clock: ``perf_counter`` at ``prerun``. Celery gives no duration.
        peak_kb: The child's high-water RSS before this task ran, so the end can
            report how much THIS task moved it rather than what a previous one
            left behind.
    """

    clock: float
    peak_kb: float


#: Where each running task began, keyed by Celery task id.
#:
#: Bounded by construction rather than by a cap: every key is written by
#: ``prerun`` and removed by ``postrun``, and ``postrun`` runs even for a task
#: that raised. The one leak Celery can produce — a task killed by the HARD
#: time limit, which SIGKILLs the process — takes this dict with it.
_started_at: dict[str, _TaskStart] = {}


def _peak_rss_kb() -> float:
    """The child's high-water resident set, as the recycler reads it.

    Taken from ``billiard.compat`` rather than read from ``/proc`` or computed
    here, and that is the whole point: this is the exact number
    ``--max-memory-per-child`` compares after every task
    (``billiard/pool.py``'s ``workloop``). Any second implementation would be a
    second opinion about what a child weighs, and the metric exists to choose
    that limit — so the two must be the same number by construction rather than
    by agreement.

    Returns:
        Kibibytes. Zero when the platform cannot answer, which is also what
        billiard treats as "unable to determine memory usage".
    """
    try:
        return float(mem_rss())
    except Exception:
        return 0.0


@setup_logging.connect  # type: ignore[untyped-decorator]
def _configure_worker_logging(**_kwargs: Any) -> None:
    """Stop Celery configuring logging, and configure it ourselves.

    Connecting to ``setup_logging`` *replaces* Celery's own setup rather than
    running before or after it — which is the only arrangement that works.
    Celery hijacks the root logger when the worker starts, so anything done
    earlier is overwritten and anything done later has already lost the lines
    emitted during startup. Those are precisely the lines being read when a
    worker will not come up.
    """
    configure_logging()
    adopt_celery_loggers()


@celeryd_init.connect  # type: ignore[untyped-decorator]
def _configure_worker_reporting(**_kwargs: Any) -> None:
    """Switch on error reporting and publish the build identity."""
    if configure_sentry(component="worker"):
        logger.info("Sentry reporting enabled for the worker.")
    set_app_info(
        version=_version(),
        environment=settings.environment,
        component="worker",
    )


def _version() -> str:
    """Return the running release, or ``unknown`` from an uninstalled tree."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("marketplace-analytic-service")
    except PackageNotFoundError:
        return "unknown"


@before_task_publish.connect  # type: ignore[untyped-decorator]
def _propagate_trace(headers: dict[str, Any] | None = None, **_kwargs: Any) -> None:
    """Copy the enqueuing context's trace id into the outgoing message.

    Runs in whichever process is *publishing* — usually an API request handler,
    sometimes another task fanning out work. When there is no context (a beat
    tick, a shell) nothing is added and the worker mints a fresh id, which is
    correct: inventing a parent would be a false claim about causation.

    Args:
        headers: The message headers Celery is about to send. Mutated in
            place; Celery protocol 2 carries custom entries through to the
            worker as attributes on ``task.request``.
    """
    trace_id = current_trace_id()
    if headers is None or trace_id is None:
        return
    headers[TRACE_HEADER] = trace_id


@task_prerun.connect  # type: ignore[untyped-decorator]
def _bind_task_context(task_id: str, task: Any = None, **_kwargs: Any) -> None:
    """Bind this execution's context and start its clock.

    Args:
        task_id: Celery's id for this execution. Distinct per retry, which is
            what makes a retried task distinguishable from the attempt before
            it in the logs.
        task: The task instance, carrying the request and its headers.
    """
    inherited = _header(getattr(task, "request", None), TRACE_HEADER)
    bind_task(
        task_id=task_id,
        task_name=getattr(task, "name", "unknown"),
        trace_id=inherited,
    )
    peak_kb = _peak_rss_kb()
    if peak_kb > 0:
        # Written here and not only at the end, because a task the kernel kills
        # never reaches the end. See `CELERY_TASK_START_MEMORY`.
        CELERY_TASK_START_MEMORY.labels(task_name=getattr(task, "name", "unknown")).observe(
            peak_kb * 1024
        )
    _started_at[task_id] = _TaskStart(clock=time.perf_counter(), peak_kb=peak_kb)


def _header(request: Any, name: str) -> str | None:
    """Read one custom header off a Celery request, whichever shape it took.

    Celery has moved this around between protocol versions and between
    ``apply_async`` and ``send_task``: the value can be an attribute on the
    request's ``Context``, an entry reachable through its ``get``, or an entry
    in a ``headers`` mapping hanging off it. All three are tried because
    silently getting ``None`` here breaks nothing visible — it just quietly
    severs the trace, which is the failure this whole module exists to prevent
    and the only one here that nothing would report.

    Args:
        request: The task's request object, or ``None``.
        name: The header name.

    Returns:
        The header value, or ``None`` when this task was not enqueued by
        anything that had a trace (a beat tick, a shell, a retry replay).
    """
    if request is None:
        return None
    candidates = [getattr(request, name, None)]
    getter = getattr(request, "get", None)
    if callable(getter):
        candidates.append(getter(name))
    headers = getattr(request, "headers", None)
    if isinstance(headers, dict):
        candidates.append(headers.get(name))
    return next((value for value in candidates if isinstance(value, str) and value), None)


@task_postrun.connect  # type: ignore[untyped-decorator]
def _record_task_outcome(
    task_id: str, task: Any = None, state: str | None = None, **_kwargs: Any
) -> None:
    """Record the task's duration and outcome, then clear its context.

    Args:
        task_id: The execution that just finished.
        task: The task instance, for its registered name.
        state: Celery's final state, e.g. ``SUCCESS`` or ``FAILURE``.
    """
    name = getattr(task, "name", "unknown")
    started = _started_at.pop(task_id, None)
    if started is not None:
        CELERY_TASK_DURATION.labels(task_name=name).observe(time.perf_counter() - started.clock)
        _record_task_memory(name, before_kb=started.peak_kb)
    CELERY_TASKS.labels(task_name=name, state=(state or "unknown").lower()).inc()
    # The next task runs in this same process. See the module docstring.
    reset_context()


def _record_task_memory(task_name: str, *, before_kb: float) -> None:
    """Record where this task left the child's water line, and how far it moved it.

    Both, because either alone misleads. A high-water mark is inherited, so the
    absolute figure blames whichever task happens to run after an expensive one;
    and the growth alone cannot say whether a child is anywhere near the limit,
    since a task that adds nothing to a child already at 500 MB is the one about
    to be recycled.

    Args:
        task_name: The task that just finished.
        before_kb: The child's high-water mark before it started.
    """
    after_kb = _peak_rss_kb()
    if after_kb <= 0:
        return
    CELERY_TASK_PEAK_MEMORY.labels(task_name=task_name).observe(after_kb * 1024)
    CELERY_TASK_MEMORY_GROWTH.labels(task_name=task_name).observe(
        max(after_kb - before_kb, 0.0) * 1024
    )


@task_failure.connect  # type: ignore[untyped-decorator]
def _record_task_failure(
    sender: Any = None, exception: BaseException | None = None, **_kwargs: Any
) -> None:
    """Count a task that raised, and separately one that was never finished.

    Separate from ``task_postrun``'s ``state`` label rather than derived from
    it: ``postrun`` reports the state Celery recorded, and a task killed by the
    soft time limit or lost to a worker restart does not always reach it. A
    failure counted in two places is a rounding error; a failure counted in
    none is a silent one.

    ``WorkerLostError`` is counted twice over for the opposite reason — it is
    not really a failure at all, it is an ABSENCE. The child died mid-run, so
    nothing unwound, nothing was logged by the task itself, and the message is
    acknowledged on the way past rather than requeued. Left inside the general
    failure rate it is unfindable: see :data:`~src.core.observability.metrics`
    ``CELERY_WORKER_LOST`` for the arithmetic.

    This handler runs in the PARENT process for that case — the child that
    would normally record it no longer exists — which is also why it cannot be
    done anywhere closer to the task.

    Args:
        sender: The task whose execution failed.
        exception: What it failed with, as Celery passes it to the signal.
    """
    name = getattr(sender, "name", "unknown")
    CELERY_TASKS.labels(task_name=name, state="failure").inc()
    if isinstance(exception, WorkerLostError):
        CELERY_WORKER_LOST.labels(task_name=name).inc()


@task_retry.connect  # type: ignore[untyped-decorator]
def _record_task_retry(sender: Any = None, **_kwargs: Any) -> None:
    """Count a retry. A rising retry rate is what WB trouble looks like first."""
    CELERY_TASKS.labels(task_name=getattr(sender, "name", "unknown"), state="retry").inc()


@worker_ready.connect  # type: ignore[untyped-decorator]
def _start_worker_exporter(**_kwargs: Any) -> None:
    """Serve this worker's metrics on its own port.

    On ``worker_ready`` rather than ``worker_init``: the port should not accept
    a scrape until the worker can actually do work, so that "the exporter
    answers" and "the worker is alive" are the same statement.

    Failures here are logged and swallowed. A worker that refuses to start
    because its metrics port is taken would trade the harvest for the
    measurement of the harvest, which is exactly the wrong way round.
    """
    if not settings.metrics_enabled:
        return
    try:
        start_http_server(settings.worker_metrics_port, registry=build_worker_registry())
    except OSError as exc:
        logger.warning(
            "Worker metrics exporter could not bind port %d: %s",
            settings.worker_metrics_port,
            exc,
        )
        return
    logger.info("Worker metrics exporter listening on :%d.", settings.worker_metrics_port)


def build_worker_registry() -> CollectorRegistry:
    """Return the registry a scrape of the worker should read.

    In multiprocess mode this is a *fresh* registry fed by
    :class:`~prometheus_client.multiprocess.MultiProcessCollector`, which reads
    every process's mmap files and aggregates them at scrape time. It
    deliberately does not include the default registry's own values: in the
    main process those are the parent's, and the parent runs no tasks, so
    including them would double-count nothing and mislead about everything.

    Outside multiprocess mode (a single-process worker, or a test) the default
    registry is already the whole truth.
    """
    if not settings.multiprocess_metrics_enabled:
        from prometheus_client import REGISTRY

        _register_worker_collectors(REGISTRY)
        return REGISTRY
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
    _register_worker_collectors(registry)
    return registry


def _register_worker_collectors(registry: CollectorRegistry) -> None:
    """Add the container's memory and metrics-tmpfs readings to a worker registry.

    Registered as collectors instead of living in
    :func:`~src.core.observability.collectors.refresh_sampled_metrics` because
    the worker has no exposition route to call it from: its exporter is
    ``prometheus_client``'s own HTTP server, which renders the registry and
    nothing else. A collector is the one hook that server does invoke.

    Duplicate registration is tolerated rather than prevented. In multiprocess
    mode the registry above is fresh every time, so this cannot fire; outside it
    (a single-process worker, a test) the registry is the shared default one and
    a second call would otherwise raise where the first had already succeeded.
    """
    # Imported here rather than at module scope: `collectors` imports this
    # package's metrics, and a local import keeps the worker's startup path thin.
    from src.core.observability.collectors import CgroupMemoryCollector, MetricsDirCollector

    for collector in (CgroupMemoryCollector(), MetricsDirCollector()):
        with contextlib.suppress(ValueError):
            registry.register(collector)


def prepare_multiprocess_dir() -> None:
    """Make sure the multiprocess directory exists. Deliberately does NOT wipe it.

    **Emptiness is the mount's job, not this function's**, and the distinction
    took a bug to find. The obvious implementation wipes the directory here so
    a restart cannot inherit the previous run's cumulative counters — which
    would make a container restart read as a traffic spike, since Prometheus
    interprets a counter that jumped rather than reset as real traffic.

    That implementation is wrong, and silently so. ``prometheus_client`` decides
    whether a metric is multiprocess-backed when the metric is *created*, and
    an unlabelled one creates its mmap file at the same moment — which is at
    import of :mod:`src.core.observability.metrics`, i.e. before this function
    can possibly run, because importing this module is what imports that one.
    Unlinking those files afterwards does not fail: on Linux the mapping
    survives the unlink, so the parent goes on writing happily to a deleted
    inode that the collector will never read. Counters that quietly stop being
    collected are precisely the failure this whole stack exists to prevent.

    So the directory is a **tmpfs mount** instead (see the ``worker`` service in
    ``docker-compose.yml``). A tmpfs is created empty at container start, which
    makes staleness impossible by construction rather than by a wipe that has
    to win a race against an import. This function only guarantees the path
    exists, for a worker run outside Docker.
    """
    directory = settings.prometheus_multiproc_dir.strip()
    if not directory:
        return
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    # prometheus_client reads this from the environment, not from an argument,
    # so it has to be exported rather than passed.
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = str(path)


@worker_process_shutdown.connect  # type: ignore[untyped-decorator]
def _mark_process_dead(pid: int | None = None, **_kwargs: Any) -> None:
    """Retire a prefork child's gauge files when it exits.

    Without this, the child's last gauge values keep being counted as a live
    process's — so a worker that has been recycled ten times reports ten
    processes' worth of pool connections, and the `live*` aggregation modes
    every gauge in :mod:`src.core.observability.metrics` declares stop meaning
    what they say.
    """
    if not settings.multiprocess_metrics_enabled or pid is None:
        return
    multiprocess.mark_process_dead(pid)  # type: ignore[no-untyped-call]


__all__ = [
    "TRACE_HEADER",
    "build_worker_registry",
    "prepare_multiprocess_dir",
]
