"""The backup's Telegram alert survives a dropped connection, and only that.

On 2026-10-07 the nightly backup failed and its alert died on one connect
timeout to api.telegram.org — a path from this host that drops a share of
connects — while the log said the request was "rejected". These tests run the
real ``alert`` in bash with ``_telegram_send`` stubbed to a scripted sequence of
curl exit codes, so what is pinned is the retry policy, not the network.

Integration rather than unit for the same reason as ``test_backup_dump_retry``:
each case forks a real bash, which the unit tier's budget does not allow.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.integration

_LIB = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "backup" / "lib"

#: Resolved once, so the call below names an absolute executable.
_BASH = shutil.which("bash") or "/bin/bash"


def _run_alert(tmp_path: pathlib.Path, *, exit_codes: list[int]) -> tuple[int, str]:
    """Run ``alert`` against a sender that returns ``exit_codes`` in turn.

    Returns how many sends were attempted and what the run logged.
    """
    codes = " ".join(str(code) for code in exit_codes)
    script = f"""
set -euo pipefail
. "{_LIB}/log.sh"
BACKUP_ALERT_TELEGRAM_BOT_TOKEN=token BACKUP_ALERT_TELEGRAM_CHAT_ID=chat
BACKUP_ALERT_RETRY_DELAY_SECONDS=0
codes=({codes})
_telegram_send() {{
    calls=$(( $(cat "{tmp_path}/calls" 2>/dev/null || echo 0) + 1 ))
    echo "$calls" > "{tmp_path}/calls"
    rc=${{codes[$((calls - 1))]}}
    [ "$rc" -eq 0 ] && printf '{{"ok":true}}'
    return "$rc"
}}
alert "❌ Backup FAILED"
"""
    # S603: the executable is resolved above and the script is this file's own
    # text, with only pytest's tmp_path and integers interpolated into it.
    result = subprocess.run(  # noqa: S603
        [_BASH, "-c", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return int((tmp_path / "calls").read_text()), result.stdout


def test_a_timed_out_send_is_retried_and_delivered(tmp_path: pathlib.Path) -> None:
    """One connect timeout (curl 28) costs a retry, not the alert."""
    calls, logged = _run_alert(tmp_path, exit_codes=[28, 0])

    assert calls == 2
    assert "WARN" not in logged


def test_an_http_rejection_is_not_retried(tmp_path: pathlib.Path) -> None:
    """A 4xx (curl 22) is a wrong token or chat id; asking again changes nothing."""
    calls, logged = _run_alert(tmp_path, exit_codes=[22, 0])

    assert calls == 1
    assert "rejected (HTTP error)" in logged


def test_a_path_that_stays_down_is_logged_as_unreachable(tmp_path: pathlib.Path) -> None:
    """The retry is bounded, and the log names the network rather than the config."""
    calls, logged = _run_alert(tmp_path, exit_codes=[28, 28, 28, 0])

    assert calls == 3
    assert "unreachable after 3 attempts (curl exit 28)" in logged
    assert "rejected" not in logged
