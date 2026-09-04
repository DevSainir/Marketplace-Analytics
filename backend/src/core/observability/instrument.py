"""The API's side of observability: HTTP metrics, ``/metrics`` and ``/healthz``.

Kept out of ``main.py`` because that file is already at the size where the next
addition costs more than it adds, and because these three things are one
subject: what this process publishes about itself.

Why ``/metrics`` is hand-rolled rather than ``Instrumentator.expose()``
---------------------------------------------------------------------
The library's own route renders the registry and returns it. This one does two
things first, and both matter.

It **refreshes the sampled gauges** (:mod:`~src.core.observability.collectors`)
so a scrape reports the pool and the queue as they are at the moment of asking
rather than whenever something last changed them. And it **checks the token**,
when one is configured.

Why the exposition is guarded at all
------------------------------------
``/metrics`` is a complete inventory: every route this API serves, every WB
surface it depends on, the shape of its traffic and the depth of its queues.
That is a reconnaissance document, and P0.2 already removed the other one —
the interactive API docs were unmounted for exactly this reason, and re-adding
a public route inventory under a different name would undo that decision by
accident.

Today the control is the network: nginx proxies ``/api/`` and nothing else, so
this route is unreachable from the internet and Prometheus reaches it over the
internal Docker network. ``METRICS_TOKEN`` is the second lock, for the day
somebody publishes the API's port or puts a second ingress in front of it.
Compared in constant time, because a token compared with ``==`` leaks its
prefix to anyone who can time the answer.
"""

from __future__ import annotations

import secrets
from typing import Final

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from prometheus_fastapi_instrumentator import Instrumentator

from src.core.config import settings
from src.core.logging import get_logger
from src.core.observability.collectors import refresh_sampled_metrics
from src.core.observability.health import check_health

logger = get_logger(__name__)

#: Routes kept out of the HTTP metrics. All three are polled on a schedule by
#: something that is not a user — Docker's healthcheck, Better Stack, and
#: Prometheus itself — so including them would bury the traffic that matters
#: under traffic that is constant by construction, and make the request-rate
#: graph a picture of the monitoring rather than of the service.
_EXCLUDED: Final[list[str]] = ["/health", "/healthz", "/metrics"]


def instrument_app(app: FastAPI) -> None:
    """Attach the HTTP metrics middleware to the application.

    Args:
        app: The FastAPI application, before it starts serving.
    """
    if not settings.metrics_enabled:
        return
    Instrumentator(
        # Exact status codes rather than `2xx`/`4xx` buckets. The cardinality
        # cost is a dozen values and the gain is that 401, 403 and 429 are
        # separable — which is the difference between "errors are up" and
        # "somebody is being throttled at the login route", the two readings
        # P1.5's backoff and P0.1's limiter are alerted on.
        should_group_status_codes=False,
        # THE CARDINALITY CONTROL, and the one that is a security property
        # rather than a housekeeping one. A request to a path with no matching
        # route would otherwise be labelled with the RAW path — so anybody
        # scanning for `/wp-admin`, `/.env`, `/admin.php` would create one
        # permanent time series per URL they tried, from outside, unauthenticated.
        # That is a memory-exhaustion primitive pointed at Prometheus. Grouped,
        # every unmatched path lands on `handler="none"` and the scan shows up
        # as a rise in one series instead.
        should_group_untemplated=True,
        should_instrument_requests_inprogress=True,
        inprogress_labels=True,
        excluded_handlers=_EXCLUDED,
    ).instrument(app)


def _token_accepted(request: Request) -> bool:
    """Whether the caller may read the exposition.

    Args:
        request: The scrape request.

    Returns:
        ``True`` when no token is configured (the network is the control), or
        when the presented bearer token matches in constant time.
    """
    expected = settings.metrics_token
    if not expected:
        return True
    header = request.headers.get("Authorization", "")
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer":
        return False
    return secrets.compare_digest(presented, expected)


def register_observability_routes(app: FastAPI) -> None:
    """Mount ``/metrics`` and ``/healthz``.

    Args:
        app: The FastAPI application.
    """

    @app.get(
        "/healthz",
        tags=["System"],
        summary="Readiness probe",
        responses={
            200: {"description": "Every dependency answered."},
            503: {"description": "At least one dependency did not."},
        },
    )
    async def healthz() -> Response:
        """Report whether this process can reach Postgres and Redis.

        Distinct from ``/health``, which is static and answers whether the
        process is alive. Docker restarts a container that fails *that* one, so
        it must not depend on a database — see
        :mod:`src.core.observability.health` for why conflating the two turns a
        database outage into a restart loop.

        Returns:
            200 with a per-dependency breakdown, or 503 with the same shape.
            The body never carries an exception, a host or a DSN (register
            P0.3).
        """
        report = await check_health()
        return JSONResponse(
            status_code=(
                status.HTTP_200_OK if report.healthy else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            content=report.as_payload(),
        )

    if not settings.metrics_enabled:
        return

    @app.get(
        settings.metrics_path,
        tags=["System"],
        summary="Prometheus exposition",
        # Absent from the schema even where the schema is served (local only,
        # per P0.2): this route is for one scraper, not for a client, and
        # advertising it in the SPA's own API description is how it ends up
        # proxied by somebody being helpful.
        include_in_schema=False,
    )
    async def metrics(request: Request) -> Response:
        """Render the registry, sampling the scrape-time gauges first.

        Returns:
            The Prometheus text exposition, or 404 when a token is configured
            and the caller did not present it.
        """
        if not _token_accepted(request):
            # 404, not 401. A 401 confirms the route exists and is worth
            # attacking; the same reasoning made an unowned workspace a 404
            # rather than a 403 in `get_current_workspace_id`. Nothing
            # legitimate ever sees this branch — Prometheus is configured with
            # the token — so there is no operator cost to the vaguer answer.
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Not Found"}
            )
        await refresh_sampled_metrics()
        return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


__all__ = ["instrument_app", "register_observability_routes"]
