"""Security metrics — controls counted where they fire.

Every one of these is a control reporting on itself, so an absent series means
the control is not running rather than that nothing has happened.
"""

from __future__ import annotations

from typing import Final

from prometheus_client import Counter, Gauge

# --------------------------------------------------------------------------- #
# Security — controls, counted where they fire.
# --------------------------------------------------------------------------- #

#: A query that reached a row-level-security-protected table without a tenant
#: bound, and was refused by PostgreSQL.
#:
#: **This should be flat at zero forever, and that is what makes it worth
#: exporting.** The policies fail closed: an unbound query raises rather than
#: returning nothing, precisely so the failure is unmissable. This counter is
#: what makes it unmissable *without a person reading logs* — one increment
#: means a code path is reaching tenant data without going through the tenancy
#: choke point, which is the exact defect RLS was installed to catch.
#: The label is ``reason``, not ``table``, and the difference was forced by
#: what PostgreSQL actually reports. The unbound-tenant failure is SQLSTATE
#: 42704 — "unrecognized configuration parameter ``app.workspace_id``" — which
#: names no relation, so a ``table`` label would read ``unknown`` on every
#: single increment and be worse than no label at all. ``reason`` separates the
#: two failures that ARE distinguishable and that mean different things:
#: ``tenant_unset`` is a code path that missed the tenancy choke point, and
#: ``policy_denied`` is one that bound the wrong tenant.
SECURITY_RLS_VIOLATIONS: Final[Counter] = Counter(
    "security_rls_violations_total",
    "Queries refused by row-level security, by why they were refused.",
    ["reason"],
)

#: Rejected authentication attempts, by why. `reason` is a closed set from the
#: auth dependency: `bad_credentials`, `rate_limited`, `backoff`,
#: `revoked_session`, `expired_token`, `invalid_token`.
#:
#: The rate at which this rises is the credential-stuffing signal P1.5's
#: backoff was built for and P2.2 named as an alerting gap. No account, address
#: or address hash is a label — the count is the alert, the identity is in the
#: logs.
SECURITY_AUTH_FAILURES: Final[Counter] = Counter(
    "security_auth_failures_total",
    "Authentication attempts refused, by reason.",
    ["reason"],
)

#: Controls currently reporting degraded (`src.core.degradation`). P1.2 built
#: the ledger and the alertable events; this is the half that lets a rule fire
#: on "the auth rate limiter and session revocation went down together"
#: without anything parsing a log line.
#:
#: `livemax` rather than `livemostrecent`: a control is degraded if ANY live
#: process sees it degraded, and the dangerous rounding is the one that reports
#: healthy because the process asked happened to be fine.
SECURITY_DEGRADED_CONTROLS: Final[Gauge] = Gauge(
    "security_degraded_controls",
    "1 while a security control is running in its degraded fallback mode.",
    ["control"],
    multiprocess_mode="livemax",
)
