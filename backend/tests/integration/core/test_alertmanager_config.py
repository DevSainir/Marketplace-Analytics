"""The rendered Alertmanager config: Watchdog reaches no one, Telegram goes via the relay.

`Watchdog` fires all the time by design. Routed to Telegram it would be a
message every few hours saying nothing is wrong — the kind of noise that gets a
chat muted, which is how the real page goes unread. It must still EXIST in
Alertmanager, because /healthz/alerts reads it there, so it goes to a receiver
with nothing in it.

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


def test_watchdog_is_routed_first_to_a_receiver_that_sends_nothing(tmp_path: Path) -> None:
    """First, and not continued: no later route may hand the heartbeat to Telegram."""
    result, config = _render(tmp_path, _TELEGRAM)

    assert result.returncode == 0, result.stderr
    first = config["route"]["routes"][0]
    assert first["matchers"] == ["alertname = Watchdog"]
    assert not first.get("continue", False)
    receiver = _receiver(config, first["receiver"])
    assert set(receiver) == {"name"}, f"the Watchdog receiver integrates with {sorted(receiver)}"


def test_the_bot_token_and_chat_arrive_intact(tmp_path: Path) -> None:
    """A token carries `:` and a chat id is negative — both break a naive sed."""
    result, config = _render(
        tmp_path, "ALERT_TELEGRAM_BOT_TOKEN=123:a-b_C\nALERT_TELEGRAM_CHAT_ID=-1001\n"
    )

    assert result.returncode == 0, result.stderr
    telegram = _receiver(config, "telegram")["telegram_configs"][0]
    assert telegram["bot_token"] == "123:a-b_C"
    assert telegram["chat_id"] == -1001
    assert "123:a-b_C" not in result.stdout + result.stderr
