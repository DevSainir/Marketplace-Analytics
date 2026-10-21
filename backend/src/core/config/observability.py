"""Metrics, error reporting and log shipping.

Three sinks, one section, because they are configured together or not at all:
Prometheus scrapes, Sentry receives, Loki collects. The register's argument for
leaving this unbuilt was that a `/metrics` nothing scrapes and a Sentry client
with no DSN are scaffolding pretending to be observability — so every switch
here is **off by default and turns itself on only when its destination
exists**. `sentry_enabled` is a computed property of whether a DSN was
supplied, not a flag somebody can set to `true` against an empty DSN.

The one exception to "off by default" is `metrics_enabled`. An exporter with no
scraper costs a route that answers in microseconds and holds a few hundred
floats; the asymmetry with Sentry is that a metric not recorded is gone
forever, while an error not reported is still in the logs. So the counters run
from the first deploy and Prometheus can start scraping history that already
exists.

Exposure. `/metrics` is an inventory of every route, every WB surface and every
tenant-shaped volume this service moves, which makes it a reconnaissance
document. It is never proxied by nginx (see `frontend/docker/nginx.conf`) —
Prometheus reaches the API on the internal Docker network, which is also the
only place the worker's exporter listens. `metrics_token` is the second lock
for the case where that topology is ever loosened.
"""

from __future__ import annotations

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings


class ObservabilitySettings(BaseSettings):
    """Prometheus exposition, Sentry reporting, and log rotation."""

    # --- Prometheus ---
    # On by default; see the module docstring for why this one is not gated on
    # a destination the way the other two are.
    metrics_enabled: bool = Field(default=True)
    metrics_path: str = Field(default="/metrics")
    #: Optional bearer token demanded by the exposition route. Empty means the
    #: network topology is the only control, which is true today and is why
    #: this is not required — but a token costs nothing and survives somebody
    #: publishing the API's port later.
    metrics_token: str = Field(default="")
    #: TCP port the Celery worker's own exporter listens on. The worker is not
    #: an ASGI app, so its counters need a server of their own; it binds inside
    #: the Docker network and is never published to the host.
    worker_metrics_port: int = Field(default=9100)
    #: Where prometheus_client's multiprocess mode keeps its mmap files. The
    #: prefork pool means the process that serves a scrape is NOT the process
    #: that counted the harvest, so the counters have to live on a filesystem
    #: both can see. Empty disables multiprocess mode (the API, which is one
    #: process, and every test).
    prometheus_multiproc_dir: str = Field(default="")

    # --- The alert path ---
    #: Where `/healthz/alerts` asks whether the `Watchdog` heartbeat is firing.
    #: The service name on the shared Docker network: the monitoring stack is a
    #: separate compose project that joins the application's network, so the
    #: API resolves it without anything being published. Absent (the stack is
    #: not running, as on a laptop) reads as "alerts are not getting out",
    #: which is the truth.
    alertmanager_url: str = Field(default="http://alertmanager:9093")

    # --- Sentry ---
    sentry_dsn: str = Field(default="")
    #: Fraction of transactions traced. Tracing is the expensive half of
    #: Sentry — this stays low because the value here is errors, not spans, and
    #: a 2 vCPU box does not have performance profiling to spare.
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    #: Fraction of ERROR-level log records forwarded as Sentry events. 1.0:
    #: an error we bothered to log is one worth a report.
    sentry_error_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    #: Sentry's own PII collection — request bodies, cookies, headers, the
    #: user's address. Left OFF, and it is not a preference: this service's
    #: request bodies carry passwords, reset codes and WB tokens, and Sentry's
    #: scrubbing is a denylist we do not control. Our `before_send`
    #: (`observability/sentry.py`) supplies the fields worth having instead.
    sentry_send_default_pii: bool = Field(default=False)

    # --- Log rotation ---
    #: When set, every line ALSO goes to this file through a size-capped
    #: rotating handler. Empty (the default, and what the containers run) means
    #: stdout only: Docker's json-file driver rotates it, which is the layer
    #: that actually protects the host's disk — see the `logging:` block every
    #: service carries in docker-compose.yml.
    log_file: str = Field(default="")
    #: Per-file ceiling. 20 MB is the top of the 10-20 MB band the disk budget
    #: allows; below ~10 MB a single harvest's DEBUG output can rotate away the
    #: startup lines that explain it.
    log_file_max_bytes: int = Field(default=20 * 1024 * 1024, ge=1024 * 1024)
    #: Rotated files kept alongside the live one, so the worst case on disk is
    #: `max_bytes * (backup_count + 1)` per process — 80 MB at the defaults.
    log_file_backup_count: int = Field(default=3, ge=0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sentry_enabled(self) -> bool:
        """Whether error reporting has somewhere to report to.

        Derived rather than configured on purpose. A separate `SENTRY_ENABLED`
        flag can disagree with the DSN, and the direction it disagrees in is
        always the same one: the flag is on, the DSN was never filled in, and
        the deployment believes it is reporting errors that nothing receives.
        """
        return bool(self.sentry_dsn.strip())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def multiprocess_metrics_enabled(self) -> bool:
        """Whether counters must be aggregated across processes on a scrape."""
        return bool(self.prometheus_multiproc_dir.strip())
