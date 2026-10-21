"""Both halves of a drain are configured, and in the order that makes them work.

A graceful shutdown is never one setting. It is an application timeout and a
container grace period that have to be read together, and each is harmless
looking on its own — which is why this reads the compose file rather than
trusting review.

For the API the pair is `--timeout-graceful-shutdown` and `stop_grace_period`.
Inverting them does not fail, log, or change anything visible: uvicorn is still
draining when Docker's timer expires, the SIGKILL drops every connection it was
holding, and the deploy that caused it reports success. That is strictly worse
than the 10s default this replaced, because the drain is what stopped the
requests being retried elsewhere.

For nginx, behind the edge, it is a floor set by the api (see the last test).

For the worker the pair is the grace period and Celery's warm shutdown, and it
has a ceiling as well as a floor: the stop has to fit inside a deploy window of
about 20 minutes, so a grace sized to cover the longest nightly task would turn
one badly timed deploy into a failed one.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import yaml

_COMPOSE = pathlib.Path(__file__).resolve().parents[3] / "docker" / "docker-compose.yml"

#: Docker's own default. A service that leaves `stop_grace_period` unset gets
#: this, which is the state every one of them was in before 2026-09-10.
_DOCKER_DEFAULT_GRACE_SECONDS = 10

#: The deploy window the worker's stop has to fit inside, about 20 minutes. The
#: worker is stopped near the end of it, after the build and both api rotations
#: have already spent their share.
_DEPLOY_JOB_BUDGET_SECONDS = 20 * 60


def _services() -> dict[str, Any]:
    """The compose file's services, with YAML anchors already resolved."""
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"]


def _grace_seconds(service: dict[str, Any]) -> int:
    """Parse a compose `stop_grace_period` into seconds.

    Compose accepts a duration string (`30s`, `2m`); the value is only ever a
    scalar here, so a small parser beats a dependency.
    """
    raw = str(service["stop_grace_period"]).strip()
    match = re.fullmatch(r"(\d+)(s|m|h)?", raw)
    assert match, f"unparseable stop_grace_period: {raw!r}"
    return int(match.group(1)) * {"s": 1, "m": 60, "h": 3600, None: 1}[match.group(2)]


def _uvicorn_graceful_timeout(service: dict[str, Any]) -> int:
    """The value uvicorn is given for `--timeout-graceful-shutdown`."""
    command = service["command"]
    return int(command[command.index("--timeout-graceful-shutdown") + 1])


def test_uvicorn_finishes_draining_before_docker_kills_it() -> None:
    """The API's drain timeout stays below the grace period that bounds it.

    If it does not, uvicorn is mid-drain when SIGKILL arrives and every request
    it was finishing is dropped — silently, and only on deploys, which is the
    hardest place to notice it.
    """
    api = _services()["api"]

    drain = _uvicorn_graceful_timeout(api)
    grace = _grace_seconds(api)

    assert drain < grace, (
        f"uvicorn drains for {drain}s inside a {grace}s grace period; "
        "SIGKILL would land on connections still being finished."
    )


def test_the_api_grace_period_is_not_dockers_default() -> None:
    """An unset grace period is the bug this pair was added to fix.

    Deleting `stop_grace_period` looks like removing a redundant line — the
    drain timeout is still there — and puts the 10s default back in force.
    """
    api = _services()["api"]

    grace = _grace_seconds(api)

    assert grace > _DOCKER_DEFAULT_GRACE_SECONDS


def test_the_worker_is_given_long_enough_for_a_warm_shutdown_to_mean_anything() -> None:
    """Celery's warm shutdown needs more than Docker's 10s to finish a task.

    Under the default, SIGTERM starts a warm shutdown that is SIGKILLed before
    any real task can complete — so the setting reads as configured and behaves
    exactly as if it were not.
    """
    worker = _services()["worker"]

    grace = _grace_seconds(worker)

    assert grace > _DOCKER_DEFAULT_GRACE_SECONDS


def test_the_worker_grace_cannot_outlast_the_deploy_that_waits_for_it() -> None:
    """A grace sized to cover the longest nightly task would fail deploys.

    The obvious "fix" for a task still being killed is to raise this until it
    covers `refresh_buyout_cohorts` (~1610s measured). That trades a rerun
    nobody sees for a deploy that dies on its own job timeout holding the stack
    half-rotated, which is the worse of the two.
    """
    worker = _services()["worker"]

    grace = _grace_seconds(worker)

    assert grace < _DEPLOY_JOB_BUDGET_SECONDS / 2


def test_a_drained_nginx_lets_the_api_finish_what_it_is_proxying() -> None:
    """nginx must wait at least as long as the api it is proxying a request to.

    Until 2026-10 this asserted the opposite — at most 3 s — because one nginx
    held :80/:443 and every second it spent stopping was a second of outage.
    Since the edge (HAProxy) went in front of two nginx, the deploy drains an
    nginx before replacing it, so stopping costs the site nothing; what it can
    still cost is the requests in flight, which the edge cannot move to the
    twin. A grace shorter than the api's cuts the client off a request the api
    was explicitly given time to finish.
    """
    services = _services()

    nginx = [_grace_seconds(services[name]) for name in ("frontend", "frontend_standby")]

    assert min(nginx) >= _grace_seconds(services["api"])
