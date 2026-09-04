"""Counting the moments row-level security refuses a query (register P2.5).

The policies fail closed on purpose: a query that reaches a tenant-scoped
table without ``app.workspace_id`` bound **raises** rather than returning zero
rows. The register's own words for why are that an empty result looks like
"this customer has no data" and gets "fixed" by deleting the scoping, while an
error is unmissable.

Unmissable by a person reading a traceback, that is. This module is what makes
it unmissable without one — an increment on a counter Prometheus scrapes, so
the first occurrence pages somebody instead of waiting to be noticed in a log.

**Observation only.** It hooks SQLAlchemy's ``handle_error`` event, which is
told about every DBAPI error and may either replace the exception or, as here,
do nothing to it. The error propagates exactly as it did before: same
exception, same traceback, same response. That is deliberate — a counter is
not worth changing how failures behave, and a monitoring hook that alters
control flow is one nobody trusts to leave enabled.

Why the engine and not an exception handler
-------------------------------------------
A FastAPI exception handler would see only the errors that reach a route. This
sees every one: a Celery task's, a background job's, a script's. The Celery
worker is precisely where an unscoped query is most likely to appear — the
nightly harvests deliberately cross workspaces and bind no tenant, so the
worker is the one runtime where "no tenant bound" is *sometimes correct*, and
therefore the one where an incorrect instance hides best.
"""

from __future__ import annotations

from typing import Any, Final

from sqlalchemy import event
from sqlalchemy.engine import Engine

from src.core.logging import get_logger
from src.core.observability.metrics import SECURITY_RLS_VIOLATIONS
from src.core.tenancy import WORKSPACE_SETTING

logger = get_logger(__name__)

#: ``undefined_object``. What PostgreSQL answers for
#: ``current_setting('app.workspace_id')`` when nothing has set it — which is
#: the exact shape of "a query reached tenant data without going through the
#: tenancy choke point".
_UNDEFINED_OBJECT: Final[str] = "42704"

#: ``insufficient_privilege``. A tenant WAS bound and the policy still refused,
#: or a grant did (the audit log's ``UPDATE`` refusal under ``marketplace_app``
#: is this code, and is a legitimate, tested outcome rather than a defect).
_INSUFFICIENT_PRIVILEGE: Final[str] = "42501"

REASON_TENANT_UNSET: Final[str] = "tenant_unset"
REASON_POLICY_DENIED: Final[str] = "policy_denied"


def _sqlstate(exc: BaseException | None) -> str | None:
    """Return the SQLSTATE an exception carries, whichever driver raised it.

    asyncpg exposes ``sqlstate``; psycopg (which Alembic uses) exposes
    ``pgcode``. Both are checked so the same hook works under the async engine
    and under a migration, rather than silently covering one of the two.

    Args:
        exc: The driver's own exception, or ``None``.

    Returns:
        The five-character SQLSTATE, or ``None`` when this was not a
        PostgreSQL error at all (a lost connection, a timeout).
    """
    for attribute in ("sqlstate", "pgcode"):
        code = getattr(exc, attribute, None)
        if isinstance(code, str) and code:
            return code
    return None


def _classify(exc: BaseException | None) -> str | None:
    """Decide whether this error is a tenancy refusal, and which kind.

    Args:
        exc: The driver's own exception.

    Returns:
        A ``reason`` label, or ``None`` when the error has nothing to do with
        tenancy and should not touch this counter.
    """
    code = _sqlstate(exc)
    if code is None:
        return None
    text = str(exc)
    if code == _UNDEFINED_OBJECT:
        # Narrowed to OUR setting. A 42704 naming some other missing object is
        # an ordinary bug, and counting it here would turn a security metric
        # into a general error counter — at which point the "this should be
        # flat at zero forever" property that makes it alertable is gone.
        return REASON_TENANT_UNSET if WORKSPACE_SETTING in text else None
    if code == _INSUFFICIENT_PRIVILEGE:
        return REASON_POLICY_DENIED
    return None


def _on_dbapi_error(context: Any) -> None:
    """Count a tenancy refusal, and say so at ERROR level.

    ERROR rather than WARNING, and the level is the decision: an ERROR record
    becomes a Sentry event through the logging integration
    (:mod:`src.core.observability.sentry`), so the first unscoped query in
    production arrives as an alert rather than as a line somebody finds later.
    A tenant boundary being tested by our own code is worth waking up for.

    Args:
        context: SQLAlchemy's ``ExceptionContext``. Nothing on it is mutated —
            returning ``None`` leaves the original exception to propagate.
    """
    reason = _classify(getattr(context, "original_exception", None))
    if reason is None:
        return
    SECURITY_RLS_VIOLATIONS.labels(reason=reason).inc()
    logger.error(
        "Row-level security refused a query (%s). A code path reached tenant "
        "data without passing the tenancy choke point.",
        reason,
        # The statement, never its parameters: the parameters are the tenant
        # data this control exists to protect, and a log line is retained for
        # longer and read by more people than the query was.
        extra={"reason": reason, "statement": str(getattr(context, "statement", ""))[:500]},
    )


def watch_for_tenancy_violations(engine: Engine) -> None:
    """Attach the observer to a synchronous engine.

    Args:
        engine: The **sync** engine. The async engine's ``.sync_engine`` is
            what carries SQLAlchemy's events; registering against the async
            wrapper silently attaches to nothing, which is the sort of failure
            that looks like "we have never had a violation".
    """
    event.listen(engine, "handle_error", _on_dbapi_error)


__all__ = [
    "REASON_POLICY_DENIED",
    "REASON_TENANT_UNSET",
    "watch_for_tenancy_violations",
]
