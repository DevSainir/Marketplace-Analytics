"""The restore rehearsal must wait for the *real* Postgres, not the init one.

The failure mode, written down: a Sunday deep check that polls `pg_isready` on
the default Unix socket gets "accepting connections", and one second later
`psql` answers:

    connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed:
    No such file or directory

Nothing is wrong with the dump. `postgres:16-alpine`'s entrypoint initialises
an empty data directory by starting a **temporary** server, running the init
steps against it, and shutting it down before exec'ing the real one — and that
temporary server listens on the socket. Such a readiness gate passes on a
server that is about to disappear; on a loaded single-CPU host the poll lands
inside that window often enough to break a run.

The temporary server runs with `listen_addresses=''`, so TCP on 127.0.0.1 is
the one question that separates it from the real one. That is a property of the
script's text, which is what this test reads — the behaviour itself belongs to
a Docker daemon no unit tier has.
"""

from __future__ import annotations

import pathlib
import re

_SCRIPT = (
    pathlib.Path(__file__).resolve().parents[3] / "scripts" / "backup" / "lib" / "verify_restore.sh"
)

#: The readiness loop: `until <gate>; do … done`, up to its `done`.
_READINESS_LOOP = re.compile(r"\n    until\b.*?\n    done\n", re.S)


def _source() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


def test_the_script_is_there_to_read() -> None:
    """Guards the guard: a moved file would pass every assertion below."""
    assert _SCRIPT.is_file(), f"{_SCRIPT} is missing"


def test_readiness_is_asked_over_tcp() -> None:
    """A socket answer is not proof; only 127.0.0.1 excludes the init server."""
    source = _source()
    gate = re.search(r"restore_check_is_really_ready\(\) \{.*?\n\}", source, re.S)
    assert gate, "the readiness gate is no longer a function of that name"

    body = gate.group(0)
    assert "pg_isready" in body, "the gate no longer asks whether Postgres is up"
    assert body.count("-h 127.0.0.1") >= 1, (
        "the readiness gate must probe 127.0.0.1 — the entrypoint's temporary "
        "init server listens on the Unix socket and would pass a socket check"
    )


def test_the_polling_loop_uses_that_gate() -> None:
    """The function is only worth anything if the `until` loop calls it."""
    loop = _READINESS_LOOP.search(_source())
    assert loop, "the readiness polling loop has gone"
    assert "restore_check_is_really_ready" in loop.group(0), (
        "the wait loop no longer calls the gate that excludes the init server"
    )


def test_no_bare_socket_readiness_check_remains() -> None:
    """A second, socket-only `pg_isready` would reopen the same window."""
    for line in _source().splitlines():
        if "pg_isready" not in line or line.lstrip().startswith("#"):
            continue
        assert "-h 127.0.0.1" in line, f"socket-only readiness check: {line.strip()}"
