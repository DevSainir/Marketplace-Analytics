"""The Telegram relay and the four files that have to agree about it.

Alertmanager reaches Telegram through a TCP relay in the host's network
(``docker/telegram-relay/haproxy.cfg``). The arrangement lives
in four files at once — the relay's config, the Alertmanager template, the
observability compose file and ``prometheus.yml`` — and every way it can drift
apart fails silently: a port that differs between the relay and ``api_url`` is
a Telegram delivery that times out, which is exactly the outage the relay was
built to end, and the alert about it would be the first one not to arrive.

Two properties here are security rather than wiring. The relay runs with the
host's network, so on a host whose firewall does not filter inbound traffic a
wildcard bind would publish it to the internet; and it must forward to Telegram
and nowhere else, or it is an open TCP relay sitting on our address.
"""

from __future__ import annotations

import ipaddress
import pathlib
import re
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml

pytestmark = pytest.mark.unit

_DOCKER = pathlib.Path(__file__).resolve().parents[3] / "docker"
_RELAY_CFG = _DOCKER / "telegram-relay" / "haproxy.cfg"
_COMPOSE = _DOCKER / "docker-compose.observability.yml"
_TEMPLATE = _DOCKER / "observability" / "alertmanager.yml.template"
_PROMETHEUS = _DOCKER / "observability" / "prometheus.yml"
_ALERTS = _DOCKER / "observability" / "alerts.yml"

#: Docker's default bridge gateway — what ``host-gateway`` resolves to.
_DOCKER0 = "172.17.0.1"

#: Telegram's own address space (AS62041): 149.154.160.0/20 and 2001:67c:4e8::/48.
_TELEGRAM_NETWORKS = (
    ipaddress.ip_network("149.154.160.0/20"),
    ipaddress.ip_network("2001:67c:4e8::/48"),
)


def _sections() -> dict[str, list[str]]:
    """The relay config as ``{"frontend from_alertmanager": [lines], ...}``, comments dropped."""
    sections: dict[str, list[str]] = {}
    current = ""
    for raw in _RELAY_CFG.read_text().splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):
            current = line.strip()
            sections[current] = []
        else:
            sections[current].append(line.strip())
    return sections


def _bind(section: str) -> tuple[str, int]:
    binds = [line for line in _sections()[section] if line.startswith("bind ")]
    assert len(binds) == 1, binds
    host, _, port = binds[0].split()[1].rpartition(":")
    return host, int(port)


def _services() -> dict[str, Any]:
    services: dict[str, Any] = yaml.safe_load(_COMPOSE.read_text())["services"]
    return services


def test_alertmanager_dials_the_port_the_relay_listens_on() -> None:
    """The port is the only thing in ``api_url`` that says "relay"; it must be the relay's."""
    template = yaml.safe_load(_TEMPLATE.read_text())
    telegram = next(r for r in template["receivers"] if r["name"] == "telegram")

    api_url = urlsplit(telegram["telegram_configs"][0]["api_url"])

    assert api_url.hostname == "api.telegram.org", "TLS must still be verified against Telegram"
    assert api_url.port == _bind("frontend from_alertmanager")[1]


def test_alertmanager_resolves_telegram_to_the_host_where_the_relay_is() -> None:
    """The name is pinned to docker0, where the relay — and nothing else — listens."""
    services = _services()

    assert "api.telegram.org:host-gateway" in services["alertmanager"]["extra_hosts"]
    assert services["telegram-relay"]["network_mode"] == "host"
    assert _bind("frontend from_alertmanager")[0] == _DOCKER0


@pytest.mark.parametrize("section", ["frontend from_alertmanager", "frontend metrics"])
def test_no_relay_listener_is_reachable_from_the_internet(section: str) -> None:
    """Host networking plus a wildcard bind would publish the port; no firewall is assumed.

    docker0's address is reachable from the containers and not from outside, and
    the source check is the second lock for anything that does reach it.
    """
    host, _ = _bind(section)

    assert host == _DOCKER0, f"{section} binds {host!r}; a wildcard here is a public port"
    assert "tcp-request connection reject unless { src 172.16.0.0/12 }" in _sections()[section]


def test_the_relay_forwards_to_telegram_and_nowhere_else() -> None:
    """Anything else would make it an open relay on our address."""
    servers = [line for line in _sections()["backend telegram"] if line.startswith("server ")]

    assert servers, "the relay has no road to Telegram"
    for server in servers:
        address = re.sub(r"^\[|\]$", "", server.split()[2].rpartition(":")[0])
        assert any(ipaddress.ip_address(address) in net for net in _TELEGRAM_NETWORKS), server


def test_the_relay_keeps_both_roads() -> None:
    """IPv6 and IPv4 fail at different moments; one family alone is the old outage."""
    addresses = [
        ipaddress.ip_address(re.sub(r"^\[|\]$", "", line.split()[2].rpartition(":")[0]))
        for line in _sections()["backend telegram"]
        if line.startswith("server ")
    ]

    assert {address.version for address in addresses} == {4, 6}


def test_prometheus_scrapes_the_relay_where_its_metrics_listen() -> None:
    """`Watchdog` reads the relay's health; an unscraped relay would read as no road at all."""
    jobs = {
        job["job_name"]: job for job in yaml.safe_load(_PROMETHEUS.read_text())["scrape_configs"]
    }
    target = jobs["telegram-relay"]["static_configs"][0]["targets"][0]

    host, _, port = target.rpartition(":")

    assert int(port) == _bind("frontend metrics")[1]
    assert f"{host}:host-gateway" in _services()["prometheus"]["extra_hosts"]


def test_watchdog_reads_the_backend_the_relay_actually_has() -> None:
    """A rule on a misspelled proxy name evaluates to nothing, and the heartbeat stops."""
    rules = [
        rule for group in yaml.safe_load(_ALERTS.read_text())["groups"] for rule in group["rules"]
    ]
    watchdog = next(rule for rule in rules if rule["alert"] == "Watchdog")

    proxies = set(re.findall(r'proxy="([^"]+)"', watchdog["expr"]))

    assert proxies == {"telegram"}
    assert "backend telegram" in _sections()
