"""The edge, the two nginx behind it, and the agreements between them.

Since 2026-10 the internet reaches the site through the edge — HAProxy in TCP
mode, holding :80 and :443 — which forwards to one of two nginx (`frontend`,
`frontend_standby`), so either can be replaced while the other serves. The
deploy's half of that is in `tests/integration/core/test_deploy_edge.py`.

What is pinned here are the facts that live in three files at once and fail
silently when they drift apart:

* **The client's address.** nginx writes `X-Real-IP` from `$remote_addr`, and
  the login limiter keys on it. Behind a TCP proxy that is the proxy's address
  — for every request — unless the edge sends PROXY protocol and nginx takes
  the address from it. Nothing errors when this breaks: every
  user simply shares one login budget, and one stranger's failed attempts lock
  everyone out. A half-done version fails differently but just as completely:
  a PROXY header nginx does not expect, or one it expects and never gets, is a
  broken request on every connection.
* **The health port.** The edge, Docker's HEALTHCHECK and nginx must name the
  same port, and it must be the one listener that does NOT expect PROXY
  protocol, because neither health checker sends it.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import pytest
import yaml

_REPO = pathlib.Path(__file__).resolve().parents[4]
_BASE = _REPO / "backend" / "docker" / "docker-compose.yml"
_E2E = _REPO / "backend" / "docker" / "docker-compose.e2e.yml"
_EDGE_CFG = _REPO / "backend" / "docker" / "edge" / "haproxy.cfg"
_DOCKERFILE = _REPO / "frontend" / "docker" / "Dockerfile"
_NGINX = {
    "production": _REPO / "frontend" / "docker" / "nginx.conf",
    "e2e": _REPO / "frontend" / "docker" / "nginx.ci.conf",
}
_NGINX_SERVICES = ("frontend", "frontend_standby")


def _services(path: pathlib.Path) -> dict[str, Any]:
    """Compose services, with YAML anchors and merge keys resolved."""
    return dict(yaml.safe_load(path.read_text(encoding="utf-8"))["services"])


def _edge_sections() -> dict[str, list[str]]:
    """haproxy.cfg as {section header: its directive lines}, comments stripped."""
    sections: dict[str, list[str]] = {}
    current = ""
    for raw in _EDGE_CFG.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line[0].isspace():
            current = line.strip()
            sections[current] = []
        else:
            sections[current].append(line.strip())
    return sections


def _edge_servers() -> list[str]:
    """Every `server` line in a backend, i.e. every connection the edge makes to nginx."""
    return [
        line
        for header, lines in _edge_sections().items()
        if header.startswith("backend ")
        for line in lines
        if line.startswith("server ")
    ]


def _forwarded_ports() -> set[int]:
    """The nginx ports the edge forwards client connections to."""
    return {int(re.search(r"\S+:(\d+)", line.split()[2]).group(1)) for line in _edge_servers()}  # type: ignore[union-attr]


def _edge_health_ports() -> set[int]:
    """The ports the edge's health checks probe, from `port N` on servers or default-server."""
    lines = [*_edge_servers()]
    for header, body in _edge_sections().items():
        if header.startswith(("backend ", "defaults")):
            lines += [line for line in body if line.startswith("default-server ")]
    return {int(port) for line in lines for port in re.findall(r"\bport\s+(\d+)", line)}


def _nginx_listens(which: str) -> list[str]:
    """Every `listen` directive in one nginx config, comments stripped."""
    text = _NGINX[which].read_text(encoding="utf-8")
    lines = (raw.split("#", 1)[0].strip() for raw in text.splitlines())
    return [line.rstrip(";") for line in lines if line.startswith("listen ")]


def _listen_port(listen: str) -> int:
    return int(re.match(r"listen\s+(?:\S+:)?(\d+)", listen).group(1))  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# Who holds the ports
# --------------------------------------------------------------------------- #
def test_only_the_edge_is_published_to_the_internet() -> None:
    """An nginx that publishes a port cannot be replaced without that port going dark.

    It would also be reachable around the edge — and an nginx that expects
    PROXY protocol, reached directly, trusts whatever address the caller writes
    into the header.
    """
    publishing = sorted(name for name, svc in _services(_BASE).items() if svc.get("ports"))

    assert publishing == ["edge"]


def test_the_edge_is_the_only_way_in_for_the_e2e_stack_too() -> None:
    """The browser tier exercises the path users take, not a shortcut around it."""
    publishing = sorted(
        name
        for name, svc in _services(_BASE).items()
        if svc.get("ports") or (_services(_E2E).get(name) or {}).get("ports")
    )

    assert publishing == ["edge"]


def test_both_nginx_serve_the_same_release_with_the_same_certificates() -> None:
    """The standby takes real traffic during every rotation; it must be the same server."""
    services = _services(_BASE)
    primary, standby = (services[name] for name in _NGINX_SERVICES)

    assert standby["image"] == primary["image"]
    assert standby["volumes"] == primary["volumes"]


def test_the_e2e_stack_never_runs_a_production_image() -> None:
    """Image tags are global to the daemon, which the nightly tier may share with production.

    A service the overlay leaves on `:latest` either runs production's image in
    the throwaway stack or — if the overlay builds it — overwrites the tag
    production restarts from.
    """
    base, e2e = _services(_BASE), _services(_E2E)

    untagged = sorted(
        name
        for name, svc in base.items()
        if str(svc.get("image", "")).startswith("marketplace-analytic-")
        and not str((e2e.get(name) or {}).get("image", "")).endswith(":e2e")
    )

    assert not untagged, f"{untagged} keep a production image tag in the e2e overlay"


# --------------------------------------------------------------------------- #
# The client's address
# --------------------------------------------------------------------------- #
def test_the_edge_sends_every_nginx_the_clients_address() -> None:
    """Without it nginx sees the edge's address on every request, and the limiter one client."""
    servers = _edge_servers()

    assert servers
    assert all(re.search(r"\bsend-proxy(-v2)?\b", line) for line in servers), servers


@pytest.mark.parametrize("which", sorted(_NGINX))
def test_every_port_the_edge_forwards_to_expects_proxy_protocol(which: str) -> None:
    """A PROXY header nginx does not expect is a garbled request on every connection."""
    forwarded = [
        listen for listen in _nginx_listens(which) if _listen_port(listen) in _forwarded_ports()
    ]

    assert forwarded
    assert all("proxy_protocol" in listen.split() for listen in forwarded), forwarded


@pytest.mark.parametrize("which", sorted(_NGINX))
def test_nginx_takes_the_client_address_from_the_proxy_header(which: str) -> None:
    """Accepting the header is not the same as believing it: $remote_addr stays the edge's.

    `real_ip_header` makes nginx replace `$remote_addr` — which X-Real-IP and
    every `limit_req` are written from — and `set_real_ip_from` says whose
    header to believe. Only the edge can reach these listeners, since no nginx
    publishes a port.
    """
    text = _NGINX[which].read_text(encoding="utf-8")

    assert re.search(r"^\s*real_ip_header\s+proxy_protocol;", text, re.M)
    assert re.search(r"^\s*set_real_ip_from\s+\S+;", text, re.M)


# --------------------------------------------------------------------------- #
# The health port
# --------------------------------------------------------------------------- #
def test_the_edge_checks_nginx_on_a_port_that_does_not_expect_a_proxy_header() -> None:
    """A health check sends no PROXY header, so on a PROXY listener it fails forever.

    The edge would then mark both nginx down and serve nothing, with both
    containers healthy as far as Docker can tell.
    """
    health = _edge_health_ports()

    assert len(health) == 1
    assert not health & _forwarded_ports()


@pytest.mark.parametrize("which", sorted(_NGINX))
def test_nginx_answers_health_checks_on_the_port_the_edge_probes(which: str) -> None:
    (port,) = _edge_health_ports()

    plain = [
        listen
        for listen in _nginx_listens(which)
        if _listen_port(listen) == port and "proxy_protocol" not in listen.split()
    ]

    assert plain, f"{which} nginx has no plain listener on the edge's health port {port}"


def test_docker_checks_nginx_on_the_same_port_as_the_edge() -> None:
    """Docker's HEALTHCHECK sends no PROXY header either; port 80 now expects one."""
    (port,) = _edge_health_ports()
    dockerfile = _DOCKERFILE.read_text(encoding="utf-8")

    probe = re.search(r"HEALTHCHECK[^\n]*\\\n\s*CMD\s+([^\n]+)", dockerfile)

    assert probe is not None
    assert f"127.0.0.1:{port}/healthz" in probe.group(1)


# --------------------------------------------------------------------------- #
# The edge itself
# --------------------------------------------------------------------------- #
def test_the_edges_admin_socket_is_not_reachable_from_the_network() -> None:
    """The runtime API can drain every server: whoever reaches it can take the site down."""
    sockets = [
        line for lines in _edge_sections().values() for line in lines if line.startswith("stats ")
    ]

    assert sockets
    assert all(re.match(r"stats socket\s+(ipv4@)?127\.0\.0\.1:\d+\b", s) for s in sockets), sockets


def test_the_internet_facing_edge_runs_without_privileges() -> None:
    """The one process every stranger talks to gets nothing it could keep if subverted."""
    edge = _services(_BASE)["edge"]

    assert edge.get("cap_drop") == ["ALL"]
    assert edge.get("read_only") is True
    assert "no-new-privileges:true" in edge.get("security_opt", [])


def test_the_edge_image_is_pinned_by_digest() -> None:
    """A tag moves; what answers on :443 must be what was reviewed and scanned."""
    edge = _services(_BASE)["edge"]

    assert re.fullmatch(r"haproxy:[\w.-]+@sha256:[0-9a-f]{64}", edge["image"]), edge["image"]
