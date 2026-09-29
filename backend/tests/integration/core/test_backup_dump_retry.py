"""The backup asks pg_dump a second time when the first one loses the server.

On 2026-09-29 the postgres container's OOM killer took a backend three minutes
into the nightly dump. The server was accepting connections again two seconds
later, and the night still went without a backup, because ``create_dump`` died
on the first non-zero exit. These tests run the real ``create_dump`` in bash
with ``pg_client`` stubbed, so what is pinned is what the function does, not
how it is spelled.

Integration rather than unit for the same reason as ``test_deploy_workflow``:
each case forks a real bash, which the unit tier's budget does not allow.
"""

from __future__ import annotations

import gzip
import pathlib
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.integration

_LIB = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "backup" / "lib"

#: Resolved once, so the call below names an absolute executable.
_BASH = shutil.which("bash") or "/bin/bash"

#: The last line pg_dump writes on success; the stub prints it when it succeeds.
_COMPLETE = "-- PostgreSQL database dump complete"


def _run_create_dump(
    tmp_path: pathlib.Path, *, failures_before_success: int
) -> subprocess.CompletedProcess[str]:
    """Run ``create_dump`` with a pg_client that fails the first N calls.

    ``alert`` is replaced after sourcing so each alert lands in a file the test
    can read, instead of trying Telegram.
    """
    script = f"""
set -euo pipefail
. "{_LIB}/log.sh"
. "{_LIB}/dump.sh"
alert() {{ printf '%s\\n---\\n' "$1" >> "{tmp_path}/alerts"; }}
pg_client() {{
    calls=$(( $(cat "{tmp_path}/calls" 2>/dev/null || echo 0) + 1 ))
    echo "$calls" > "{tmp_path}/calls"
    if [ "$calls" -le {failures_before_success} ]; then
        echo "pg_dump: error: server closed the connection unexpectedly" >&2
        return 1
    fi
    printf 'CREATE TABLE t ();\\n{_COMPLETE}\\n'
}}
POSTGRES_DB=marketplace POSTGRES_USER=marketplace BACKUP_PG_HOST=postgres
BACKUP_DUMP_ATTEMPTS=2
BACKUP_DUMP_RETRY_DELAY_SECONDS=0
create_dump "{tmp_path}/dump.sql.gz"
"""
    # S603: the executable is resolved above and the script is this file's own
    # text, with only pytest's tmp_path interpolated into it.
    return subprocess.run(  # noqa: S603
        [_BASH, "-c", script], capture_output=True, text=True, timeout=30
    )


def test_a_dump_that_loses_the_server_once_is_retried_and_kept(tmp_path: pathlib.Path) -> None:
    """One lost connection costs a retry, not the night's backup — and says so."""
    result = _run_create_dump(tmp_path, failures_before_success=1)

    assert result.returncode == 0, result.stdout + result.stderr
    dump = gzip.decompress((tmp_path / "dump.sql.gz").read_bytes()).decode()
    assert _COMPLETE in dump
    alerts = (tmp_path / "alerts").read_text()
    assert "needed attempt 2" in alerts
    assert "FAILED" not in alerts


def test_a_dump_that_fails_every_attempt_still_fails_the_run(tmp_path: pathlib.Path) -> None:
    """The retry is bounded: a server that stays down is a failed backup, alerted as one."""
    result = _run_create_dump(tmp_path, failures_before_success=2)

    assert result.returncode != 0
    assert "Backup FAILED" in (tmp_path / "alerts").read_text()
    assert (tmp_path / "calls").read_text().strip() == "2"
