"""Error reporting for both runtimes, with the same redaction as the logs.

Sentry is the sink P2.1 named and left open, and the register's condition for
building it was that the destination exist first. So this module does nothing
at all without a DSN: :attr:`Settings.sentry_enabled` is *derived* from whether
one was supplied, which is what stops a deployment believing it reports errors
that nothing receives.

**Why it is initialised twice.** The API and the Celery worker are separate
processes with separate entrypoints, and the worker is the half that matters
more here — an exception in a request is answered with a 500 that somebody
notices, while an exception in the nightly harvest is a night of missing data
that surfaces as a customer asking why a number is stale. Wiring only FastAPI
would instrument the failures that already have a witness.

**What is sent, and what is refused.**

``send_default_pii`` is off, and that is a security decision rather than a
privacy preference: with it on, Sentry attaches request bodies, headers and
cookies, and on this API those carry passwords, reset codes, refresh cookies
and WB seller tokens. Its own scrubbing is a denylist maintained by somebody
else, applied to data we should not have transmitted in the first place.

What replaces it is deliberate and small: the log context —
trace id, tenant, workspace, account, route — attached as tags, so a report
answers "whose, and during what" without carrying anything a caller submitted.

``before_send`` runs the same :func:`scrub_event` the log pipeline runs. One
function, two sinks, so a pattern added for the logs cannot be forgotten
here — which is the harder direction to notice, because nobody greps Sentry
for secrets that should not be in it.
"""

from __future__ import annotations

import logging
from importlib.metadata import PackageNotFoundError, version
from typing import Any, cast

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.types import Event, Hint

from src.core.config import settings
from src.core.logcontext import current_context
from src.core.logging import get_logger
from src.core.observability.scrubbing import scrub_event

logger = get_logger(__name__)

#: Tags worth putting on every report, drawn from the log context. Tags rather
#: than extra data because Sentry indexes tags: "every error for this tenant"
#: and "every error on this trace" become searches instead of scrolling.
_CONTEXT_TAGS: tuple[str, ...] = (
    "trace_id",
    "request_id",
    "task_id",
    "task_name",
    "organization_id",
    "workspace_id",
    "path",
    "method",
)


def _release() -> str:
    """Return the deployed version, for grouping reports by release.

    Read from the installed package metadata rather than a constant, so it
    tracks the version Release Please writes into ``pyproject.toml`` (see
    ``docs/RELEASES.md``) and cannot be a number somebody forgot to bump.
    """
    try:
        return version("marketplace-analytics")
    except PackageNotFoundError:
        # Running from a source tree that was never installed — a developer's
        # checkout. An unknown release is better than refusing to report.
        return "unknown"


def _before_send(event: Event, _hint: Hint) -> Event | None:
    """Redact the report and attach who it happened to.

    Args:
        event: Sentry's event payload, about to leave the process.
        _hint: Sentry's originating exception info; unused.

    Returns:
        The scrubbed event. Never ``None`` — dropping an event here would mean
        losing an error to protect it, and the scrubber already guarantees the
        payload is safe to send.
    """
    context = current_context()
    tags = event.setdefault("tags", {})
    if isinstance(tags, dict):
        for name in _CONTEXT_TAGS:
            value = context.get(name)
            if value is not None:
                tags.setdefault(name, value)
    # The account as an id and nothing else. `send_default_pii` being off means
    # Sentry adds no address or IP of its own, and this does not add one back:
    # the id is enough to find the person in our own database, and is not
    # itself a way to reach them.
    user_id = context.get("user_id")
    if user_id is not None:
        event.setdefault("user", {})
        if isinstance(event["user"], dict):
            event["user"].setdefault("id", user_id)
    # `Event` is a TypedDict, so mypy will not let a plain dict back in even
    # though that is exactly what it is at runtime. The scrubber is deliberately
    # typed over ordinary mappings — it is shared with the log pipeline, which
    # has no Sentry types — so the cast is where the two type worlds meet.
    return cast(Event, scrub_event(dict(event)))


def _integrations(*, component: str) -> list[Any]:
    """Return the integrations this component should install.

    Args:
        component: ``api`` or ``worker``.

    Returns:
        The integration list. SQLAlchemy and logging are shared; the transport
        integration differs because only one of the two processes has one.
    """
    shared: list[Any] = [
        SqlalchemyIntegration(),
        # Log records become Sentry data at two different levels: everything
        # from INFO up is kept as a breadcrumb (the trail leading to the
        # error), and ERROR and above additionally becomes an event of its own.
        # That second half is what makes `logger.error(...)` in a `except`
        # block reportable without any call site importing Sentry.
        LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
    ]
    if component == "worker":
        # `monitor_beat_tasks` off: it registers cron monitors against Sentry's
        # crons product, which is a second paid surface and a second place for
        # the schedule to be defined. The beat schedule lives in
        # `src.core.celery_app` and its health is already visible as
        # `celery_tasks_total` — one source of truth beats two that can
        # disagree.
        return [*shared, CeleryIntegration(monitor_beat_tasks=False)]
    # Starlette rather than FastAPI: the FastAPI integration adds dependency
    # -resolution spans that are only useful with tracing on, and tracing is
    # off by default on a 2 vCPU box.
    return [*shared, StarletteIntegration()]


def configure_sentry(*, component: str) -> bool:
    """Initialise Sentry for this process, if a DSN was configured.

    Idempotent by way of Sentry's own client: calling twice replaces the
    client rather than stacking two, so a re-forked worker is harmless.

    Args:
        component: ``api``, ``worker`` or ``beat`` — becomes a tag on every
            report, so a graph or a search can separate a failing request from
            a failing harvest.

    Returns:
        ``True`` when reporting was switched on, ``False`` when there was no
        DSN to report to. Returned rather than logged-and-swallowed so the
        caller can say which of the two happened at startup — "Sentry
        disabled" in the boot log is a fact worth having when errors later
        fail to appear.
    """
    if not settings.sentry_enabled:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=_release(),
        integrations=_integrations(component=component),
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=settings.sentry_send_default_pii,
        before_send=_before_send,
        # Belt and braces with `send_default_pii=False` above. That flag is
        # what stops bodies being attached; this refuses to attach one even if
        # a future default, or a `send_default_pii` somebody flips to debug a
        # problem, would otherwise allow it. On this API a captured request
        # body is a password or a WB token, so the two controls are worth
        # having independently — the same argument the audit log's
        # grant-and-trigger pair rests on.
        max_request_body_size="never",
    )
    sentry_sdk.set_tag("component", component)
    return True


__all__ = ["configure_sentry"]
