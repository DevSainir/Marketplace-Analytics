"""Metrics, error reporting, health and log redaction.

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

import os


def _normalise_multiprocess_env() -> None:
    """Delete ``PROMETHEUS_MULTIPROC_DIR`` when it is set to an empty string.

    **This runs before anything in this package imports ``prometheus_client``,
    and that ordering is the entire fix.** The library resolves its value class
    at ITS OWN import — ``ValueClass = get_value_class()`` is a module-level
    assignment in ``prometheus_client.values`` — by asking whether the variable
    is *present*, not whether it has a value. Its own source note says the
    choice "needs to be chosen before the first metric is constructed"; in
    practice it is chosen even earlier than that.

    So an empty-but-present variable puts every metric into multiprocess mode
    against a path of ``""``. This module is the only door: nothing outside
    ``src.core.observability`` imports ``prometheus_client``, and importing any
    submodule runs this ``__init__`` first — so normalising here is guaranteed
    to happen before the library forms an opinion. The first version of this fix
    lived in ``metrics.py`` and was already too late: the variable was deleted
    after ``ValueClass`` had been bound, which turned a clear startup error into
    a ``TypeError`` deep inside mmap file creation.

    Empty-but-present is not an exotic input. It is what `.env.example` produces
    the moment a variable is listed with no value — which is how a reader is
    meant to see that a setting exists — and CI's end-to-end job copies that
    file to `.env` verbatim. It crashed every API container there while passing
    every test on a developer's machine, where the variable is simply absent.

    Deleting rather than defaulting: absent and empty must mean the same thing,
    and the only way to say "absent" to a library that tests for presence is to
    make it absent.
    """
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR", "").strip():
        return
    os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)
    os.environ.pop("prometheus_multiproc_dir", None)


_normalise_multiprocess_env()

from src.core.observability.scrubbing import (  # noqa: E402 — see above: the
    # environment must be normalised before any import that reaches
    # prometheus_client, so this one deliberately does not sit at the top.
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
