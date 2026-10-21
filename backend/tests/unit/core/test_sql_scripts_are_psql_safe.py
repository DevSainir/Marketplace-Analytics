"""The operator SQL scripts must survive the tool that actually runs them.

`least_privilege_role.sql` is applied by hand through **psql**, and psql has a
rule no other client shares: it substitutes `:variables` in the SQL it sends —
but *not* inside a dollar-quoted block. Text between `$$` and `$$` reaches the
server verbatim.

A script that builds its `CREATE ROLE ... PASSWORD :'app_password'` inside a
`DO $$ ... $$` block therefore fails: psql passes the literal `:'app_password'`
through and PostgreSQL answers `syntax error at or near ":"`.

The integration test covering that script does not catch it, and cannot: it
replaces the variable in Python before executing, because it drives asyncpg
rather than psql. It tests the grants — which is what it is for — and is blind
to the substitution rule. This closes that specific gap by reading the file.
"""

from __future__ import annotations

import pathlib
import re

_SQL_DIR = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "sql"

#: ``$$ ... $$`` — the region psql passes through untouched.
_DOLLAR_BLOCK = re.compile(r"\$\$.*?\$\$", re.S)

#: A psql variable reference, quoted (``:'x'``) or bare (``:x``). The lookbehind
#: excludes PostgreSQL's ``::`` cast — `name::regclass` and `::uuid` are not
#: variables, and matching them would make this fail on correct scripts.
_PSQL_VAR = re.compile(r"(?<![:\w]):'?[a-zA-Z_][a-zA-Z0-9_]*'?")


def _scripts() -> list[pathlib.Path]:
    """Every operator SQL script."""
    return sorted(_SQL_DIR.glob("*.sql"))


def test_there_are_scripts_to_check() -> None:
    """Guards the guard: an empty glob would pass everything below."""
    assert _scripts(), f"no .sql scripts found under {_SQL_DIR}"


def test_no_psql_variable_is_used_inside_a_dollar_quoted_block() -> None:
    """The exact failure described above, encoded.

    Anything needing a variable has to sit outside ``$$``, which is why the role
    script now sets the password with a plain ``ALTER ROLE`` and creates the
    role through ``\\gexec`` rather than building both inside a ``DO`` block.
    """
    offenders: list[str] = []
    for script in _scripts():
        for block in _DOLLAR_BLOCK.findall(script.read_text()):
            offenders.extend(f"{script.name}: {found}" for found in _PSQL_VAR.findall(block))

    assert offenders == [], (
        "psql does not substitute variables inside $$ ... $$ — these would reach "
        f"PostgreSQL verbatim and fail as a syntax error: {offenders}"
    )
