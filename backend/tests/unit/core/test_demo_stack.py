"""`make demo` must stay a stack of its own, and stay what a laptop can run.

The demo runs the real topology with three deliberate differences, each of
which is one innocent-looking edit from coming undone:

* its own Compose project — the seed EMPTIES the database it is pointed at, so
  sharing a project with a development stack would empty that stack's data;
* the plain-HTTP nginx under its own image tag — the production config refuses
  to load without a certificate, and the base file's `:latest` names that build;
* no scheduler — every scheduled task asks WildBerries for something with a
  token the demo does not have.

Read straight from the files, so the failure names the line that changed.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import pytest
import yaml

_ROOT = pathlib.Path(__file__).resolve().parents[4]
_DEMO = _ROOT / "backend" / "docker" / "docker-compose.demo.yml"
_MAKEFILE = _ROOT / "Makefile"


def _services() -> dict[str, Any]:
    """The demo overlay's services."""
    return dict(yaml.safe_load(_DEMO.read_text())["services"])


def _compose_demo() -> str:
    """The Makefile's ``COMPOSE_DEMO`` definition, continuation lines joined."""
    text = _MAKEFILE.read_text().replace("\\\n", " ")
    match = re.search(r"^COMPOSE_DEMO := (.+)$", text, flags=re.MULTILINE)
    assert match, "the Makefile no longer defines COMPOSE_DEMO"
    return match.group(1)


def test_the_demo_is_a_compose_project_of_its_own() -> None:
    """Never the base project, and never with the developer's local override."""
    command = _compose_demo()

    assert "-p $(DEMO_PROJECT)" in command
    assert re.search(r"^DEMO_PROJECT := marketplace-analytics-demo$", _MAKEFILE.read_text(), re.M)
    assert "override" not in command


def test_the_demo_listens_on_loopback_only() -> None:
    """A demo on a laptop is not served to the café's Wi-Fi."""
    command = _compose_demo()

    assert "FRONTEND_HTTP_PORT=127.0.0.1:" in command
    assert "FRONTEND_HTTPS_PORT=127.0.0.1:" in command


@pytest.mark.parametrize("service", ["frontend", "frontend_standby"])
def test_nginx_is_the_plain_http_build_under_its_own_tag(service: str) -> None:
    """The TLS build cannot start without a certificate; `:latest` is that build."""
    nginx = _services()[service]

    assert nginx["build"]["target"] == "e2e"
    assert str(nginx["image"]).endswith(":demo")


def test_the_scheduler_does_not_start() -> None:
    """A profile nobody activates keeps beat down; the worker still answers buttons."""
    services = _services()

    assert services["beat"]["profiles"]
    assert "worker" not in services or "profiles" not in services["worker"]
