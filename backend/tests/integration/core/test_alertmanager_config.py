"""The rendered Alertmanager config: the heartbeat goes out, and never to Telegram.

`Watchdog` fires all the time by design. Routed anywhere but the heartbeat
receiver it would be a Telegram message every few hours saying nothing is
wrong — the kind of noise that gets a chat muted, which is how the real page
goes unread. And the heartbeat URL is the one piece of this file an operator
types by hand, so the renderer's handling of it is checked here with the
characters a URL actually contains.

Integration tier for the same reason as the deploy script tests: it forks a
real bash and awk, and needs nothing else.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

BACKEND = Path(__file__).resolve().parents[3]
RENDERER = BACKEND / "scripts" / "observability" / "render_alertmanager_config.sh"
TEMPLATE = BACKEND / "docker" / "observability" / "alertmanager.yml.template"
HEARTBEAT = "https://uptime.example.test/api/v1/heartbeat/abc?source=am&x=1"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _render(tmp_path: Path, env: str) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    """Render into a copy of the backend tree whose .env is ``env``."""
    (tmp_path / "scripts" / "observability").mkdir(parents=True)
    (tmp_path / "docker" / "observability").mkdir(parents=True)
    shutil.copy(RENDERER, tmp_path / "scripts" / "observability")
    shutil.copy(TEMPLATE, tmp_path / "docker" / "observability")
    (tmp_path / ".env").write_text(env, encoding="utf-8")
    result = subprocess.run(  # noqa: S603 - a script from this repository
        ["bash", str(tmp_path / "scripts" / "observability" / RENDERER.name)],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = tmp_path / "docker" / "observability" / "alertmanager.yml"
    config = yaml.safe_load(output.read_text()) if output.exists() else {}
    return result, config


_TELEGRAM = "ALERT_TELEGRAM_BOT_TOKEN=123:abc\nALERT_TELEGRAM_CHAT_ID=-100\n"


def _receiver(config: dict[str, Any], name: str) -> dict[str, Any]:
    return next(r for r in config["receivers"] if r["name"] == name)


def test_the_heartbeat_url_arrives_intact_and_watchdog_goes_only_there(tmp_path: Path) -> None:
    result, config = _render(tmp_path, _TELEGRAM + f"ALERT_HEARTBEAT_URL={HEARTBEAT}\n")

    assert result.returncode == 0, result.stderr
    first = config["route"]["routes"][0]
    assert first["matchers"] == ["alertname = Watchdog"]
    assert first["receiver"] == "heartbeat"
    assert not first.get("continue", False)
    webhook = _receiver(config, "heartbeat")["webhook_configs"][0]
    assert webhook["url"] == HEARTBEAT
    assert webhook["send_resolved"] is False


def test_without_a_heartbeat_url_it_renders_says_so_and_still_keeps_watchdog_off_telegram(
    tmp_path: Path,
) -> None:
    result, config = _render(tmp_path, _TELEGRAM)

    assert result.returncode == 0, result.stderr
    assert "ALERT_HEARTBEAT_URL is not set" in result.stderr
    assert "webhook_configs" not in _receiver(config, "heartbeat")
    assert config["route"]["routes"][0]["receiver"] == "heartbeat"


def test_a_heartbeat_url_that_is_not_https_is_refused(tmp_path: Path) -> None:
    result, _ = _render(tmp_path, _TELEGRAM + "ALERT_HEARTBEAT_URL=http://plain.test/beat\n")

    assert result.returncode != 0
    assert "https://" in result.stderr
