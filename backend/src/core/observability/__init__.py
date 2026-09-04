"""Metrics, error reporting, health and log redaction (register P2.1, P2.2).

**A deliberately thin facade.** Only :mod:`~src.core.observability.scrubbing`
is re-exported here; every other submodule is imported from its own path.

That is not an oversight, it is an import-cycle rule with a reason. The
redaction processor is used by :mod:`src.core.logging`, which is imported by
practically everything in this backend — including the metrics, Sentry and
health modules in this same package. A facade that eagerly imported those would
make ``import src.core.logging`` depend on them and them on it, and the failure
would not be a tidy cycle error: it would be an ``ImportError`` at container
start, in the one subsystem whose job is to explain container starts.

So the rule is: this package may import from ``src.core`` freely EXCEPT in
:mod:`~src.core.observability.scrubbing`, which imports nothing from the
application at all and is therefore always safe to reach from the logging
configuration.

* :mod:`~src.core.observability.scrubbing` — credential redaction, shared by
  the log pipeline and Sentry.
* :mod:`~src.core.observability.metrics` — every metric this service exports.
* :mod:`~src.core.observability.collectors` — gauges sampled at scrape time
  (the connection pool, the Celery queues).
* :mod:`~src.core.observability.instrument` — the FastAPI wiring and the
  guarded ``/metrics`` route.
* :mod:`~src.core.observability.celery_runtime` — the worker's exporter, its
  task-boundary context, and trace propagation from the enqueuing request.
* :mod:`~src.core.observability.sentry` — error reporting for both runtimes.
* :mod:`~src.core.observability.health` — the dependency checks behind
  ``/healthz``.
"""

from src.core.observability.scrubbing import (
    REDACTED,
    is_sensitive_key,
    scrub_event,
    scrub_text,
    scrub_value,
)

__all__ = [
    "REDACTED",
    "is_sensitive_key",
    "scrub_event",
    "scrub_text",
    "scrub_value",
]
