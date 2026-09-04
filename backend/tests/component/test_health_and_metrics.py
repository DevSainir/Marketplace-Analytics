"""The two endpoints this service publishes about itself (register P2.1/P2.2).

``/healthz`` is what an external uptime checker polls, and ``/metrics`` is what
Prometheus scrapes. Both are unauthenticated in the sense that no session is
required, which is why what they say — and refuse to say — is worth pinning at
the component tier, driving the real application rather than the functions
behind it.

Three properties, and the second is the one that would be quietly lost:

* ``/healthz`` reports readiness and answers 503 when a dependency is gone,
  because an external checker's only job is to notice that.
* it never carries an exception, a host or a DSN. P0.3 removed exactly this
  class of disclosure from the API's error path, and a public probe is the
  easiest place to put it back without noticing.
* ``/metrics`` cannot be turned into an unbounded series generator by a
  stranger requesting made-up URLs.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from src.core.observability import health
from tests.component.conftest import CapturingHandler


async def test_healthz_reports_every_dependency(client: httpx.AsyncClient) -> None:
    """The probe names what it checked, so a red check is actionable."""
    # Act
    response = await client.get("/healthz")

    # Assert
    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert set(payload["dependencies"]) == {"postgres", "redis"}
    assert payload["dependencies"]["postgres"]["status"] == "ok"


async def test_healthz_answers_503_when_a_dependency_is_gone(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A readiness probe that answers 200 while Redis is down is decorative.

    Redis in particular: without it the API still SERVES, with the auth rate
    limiter and session revocation failing open (register P1.2). That is a
    security posture change wearing the costume of a healthy service, and it is
    exactly what an external checker should be shouting about.
    """

    # Arrange
    async def _refuse() -> None:
        raise ConnectionError("redis is not answering")

    monkeypatch.setattr(health, "_ping_redis", _refuse)

    # Act
    response = await client.get("/healthz")

    # Assert
    payload = response.json()
    assert response.status_code == 503
    assert payload["status"] == "degraded"
    assert payload["dependencies"]["redis"]["status"] == "down"
    # Postgres is still fine, and the probe says so rather than collapsing to
    # one flat "unhealthy" — which half is broken is most of the first minute.
    assert payload["dependencies"]["postgres"]["status"] == "ok"


async def test_a_failing_probe_discloses_nothing_about_the_infrastructure(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exception goes to the logs; the response gets a status and a number.

    This is a PUBLIC endpoint — Better Stack polls it from outside the network,
    so anyone can. A driver error here names a host, a role, a database and
    sometimes a DSN with credentials in it, and P0.3 exists because upstream
    error text used to reach clients on the ordinary error path.
    """

    # Arrange
    async def _refuse() -> None:
        raise ConnectionError(
            "could not connect to postgresql://marketplace:s3cret@postgres:5432/marketplace"
        )

    monkeypatch.setattr(health, "_ping_postgres", _refuse)

    # Act
    response = await client.get("/healthz")

    # Assert
    body = response.text
    assert response.status_code == 503
    assert "s3cret" not in body
    assert "postgresql://" not in body
    assert "marketplace" not in body
    assert "ConnectionError" not in body
    # What it DOES say stays useful.
    assert response.json()["dependencies"]["postgres"]["status"] == "down"


async def test_the_probes_are_kept_out_of_the_request_log(
    client: httpx.AsyncClient, captured_log: CapturingHandler
) -> None:
    """Polled forever by machines, so logging them would drown the log.

    Between Docker's healthcheck, Better Stack and Prometheus, these three
    paths are hit continuously and by nothing that is a user. A request log
    that includes them is mostly a record of the monitoring watching the
    service.
    """
    # Act
    await client.get("/health")
    await client.get("/healthz")
    await client.get("/metrics")

    # Assert
    paths = [payload.get("path") for payload in captured_log.payloads()]
    assert paths == []


async def test_metrics_exposes_the_registry(client: httpx.AsyncClient) -> None:
    """A scrape returns Prometheus text exposition, not JSON."""
    # Act
    response = await client.get("/metrics")

    # Assert
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# TYPE" in response.text


async def test_metrics_reports_the_pool_as_it_is_at_the_moment_of_asking(
    client: httpx.AsyncClient,
) -> None:
    """The sampled gauges are refreshed by the scrape, not by a background job.

    A gauge maintained elsewhere reports whenever something last changed it,
    which for "how full is the pool" is the wrong question — a scrape is the
    only moment the answer is needed and the only moment it is asked.
    """
    # Act
    response = await client.get("/metrics")

    # Assert
    assert "postgres_pool_connections_used" in response.text
    assert "security_degraded_controls" in response.text


async def test_a_url_a_stranger_invents_cannot_create_a_series(
    client: httpx.AsyncClient,
) -> None:
    """The cardinality control that is a security control.

    Unmatched paths are grouped under ``handler="none"``. Without that, anybody
    scanning for ``/wp-admin``, ``/.env`` and friends would add one permanent
    time series per URL they tried — unauthenticated, from the internet, into
    the memory of a process sharing a 3.8 GB box with Postgres.
    """
    # Act
    for path in ("/wp-admin", "/.env", "/admin.php", "/api/v1/nonexistent"):
        await client.get(path)
    response = await client.get("/metrics")

    # Assert
    assert 'handler="none"' in response.text
    for path in ("/wp-admin", "/.env", "/admin.php"):
        assert f'handler="{path}"' not in response.text


async def test_the_exposition_is_absent_from_the_public_schema(app: FastAPI) -> None:
    """`/metrics` is for one scraper, and is not advertised to clients.

    The schema is served only locally (P0.2 unmounted it everywhere else), so
    this is not itself the control — the control is that nginx does not proxy
    the route. It is here so that nobody, reading the SPA's own API
    description, is helpfully led to proxy it.
    """
    # Act
    schema = app.openapi()

    # Assert
    assert "/metrics" not in schema["paths"]
    # The readiness probe IS advertised: an uptime checker is a legitimate
    # client of it, and there is nothing about it to withhold.
    assert "/healthz" in schema["paths"]
