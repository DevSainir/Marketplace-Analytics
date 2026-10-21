"""No operator SQL script sets a password while Postgres is logging it.

The stack runs Postgres with `log_statement=ddl` (docker-compose.yml), and
`ALTER ROLE ... PASSWORD` is DDL. A script that sets a
role's password with that left on writes the password in clear to the container
log, and Alloy ships the container log to Loki. Nothing fails and nothing looks
wrong: the secret simply joins the log store.

`least_privilege_role.sql` is meant to be re-run after migrations, so a script
that predates the logging setting carries this exposure on every re-run until it
is guarded. This reads the files rather than trusting the next script's author
to know.
"""

from __future__ import annotations

import pathlib
import re

_SQL_DIR = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "sql"

_SETS_PASSWORD = re.compile(r"^\s*(ALTER|CREATE)\s+(ROLE|USER)\b.*\bPASSWORD\b", re.I)
_LOGGING_OFF = re.compile(r"^\s*SET\s+(LOCAL\s+)?log_statement\s*=\s*'none'\s*;", re.I)
_LOGGING_BACK = re.compile(r"^\s*(RESET\s+log_statement|SET\s+(LOCAL\s+)?log_statement\b)", re.I)


def _unguarded_password_lines(sql: str) -> list[int]:
    """Return the line numbers that set a password with statement logging on."""
    offenders: list[int] = []
    logging_off = False
    for number, line in enumerate(sql.splitlines(), start=1):
        if line.lstrip().startswith("--"):
            continue
        if _LOGGING_OFF.match(line):
            logging_off = True
        elif _LOGGING_BACK.match(line):
            logging_off = False
        elif _SETS_PASSWORD.match(line) and not logging_off:
            offenders.append(number)
    return offenders


def test_the_check_recognises_an_unguarded_password() -> None:
    """Guards the guard: the bare statement must be caught."""
    sql = "ALTER ROLE r LOGIN PASSWORD :'p';"

    assert _unguarded_password_lines(sql) == [1]


def test_the_check_accepts_a_guarded_password() -> None:
    """Logging off before, back on after, is the shape the scripts use."""
    sql = "SET log_statement = 'none';\nALTER ROLE r PASSWORD :'p';\nRESET log_statement;"

    assert _unguarded_password_lines(sql) == []


def test_no_script_sets_a_password_with_logging_on() -> None:
    """Every operator script turns statement logging off around its password."""
    offenders = {
        script.name: lines
        for script in sorted(_SQL_DIR.glob("*.sql"))
        if (lines := _unguarded_password_lines(script.read_text()))
    }

    assert offenders == {}, (
        "these lines would write a password to the Postgres log, and from there to Loki: "
        f"{offenders}"
    )
