"""The application's database role can read and write, and nothing else (P2.4).

`scripts/sql/least_privilege_role.sql` is applied by hand, once, on a box these
tests cannot reach — which is exactly the kind of artefact that rots. A SQL file
nobody executes is a plan; these cases execute it against a real PostgreSQL and
then *connect as the role it creates*, so the grants are asserted rather than
described.

The interesting assertions are the refusals. A role that can `SELECT` is easy to
get right and easy to notice when it is wrong. A role that can still `DROP TABLE`
looks identical in every test that does not try it.

This is also what finishes P1.3. The audit log's append-only property is carried
by a trigger, which stops the application but not the owner; the `REVOKE` in its
migration is inert while the application *is* the owner. Under this role the
revoke becomes a second, independent layer — so the last case here is the one
that matters most: the application cannot edit the audit trail even if the
trigger were dropped.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration

APP_ROLE = "marketplace_app_test"
APP_PASSWORD = "test-only-not-a-real-secret"

_SQL_FILE = (
    pathlib.Path(__file__).resolve().parents[3] / "scripts" / "sql" / "least_privilege_role.sql"
)

#: The role that owns the test schema — the local Postgres superuser, which is
#: what `ALTER DEFAULT PRIVILEGES FOR ROLE` has to name.
_OWNER = "marketplace"


def _split_statements(sql: str) -> list[tuple[str, bool]]:
    """Split SQL into ``(statement, is_gexec)``, respecting dollar quoting.

    Two psql behaviours have to be emulated, and each one cost a real failure by
    being absent.

    ``DO $$ ... $$`` blocks contain semicolons of their own, so splitting
    naively cuts them in half and the role is never created — which surfaces as
    "role does not exist" several steps later, a long way from the cause.

    ``\\gexec`` runs whatever the preceding query *returned* as SQL. The role
    script uses it so that `CREATE ROLE` happens only when the role is absent
    (psql cannot substitute a variable inside a dollar-quoted block, so the
    guard cannot be a ``DO`` block). Skipping the metacommand silently turns
    that statement into a plain ``SELECT`` that creates nothing.
    """
    statements: list[tuple[str, bool]] = []
    current: list[str] = []
    in_dollar = False
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        if stripped == "\\gexec":
            # Applies to the statement just collected, which psql accepts
            # without a trailing semicolon.
            body = "\n".join(current).strip().rstrip(";")
            if body:
                statements.append((body, True))
            current = []
            continue
        if line.startswith("\\"):
            continue  # any other metacommand (\set) has no effect here
        if line.count("$$") % 2 == 1:
            in_dollar = not in_dollar
        current.append(line)
        if not in_dollar and line.rstrip().endswith(";"):
            statements.append(("\n".join(current).strip().rstrip(";"), False))
            current = []
    tail = "\n".join(current).strip().rstrip(";")
    if tail:
        statements.append((tail, False))
    return [(body, gexec) for body, gexec in statements if body.strip()]


def _script_for_tests() -> list[tuple[str, bool]]:
    """Return the shipped script's statements, retargeted at the test role.

    The file is READ rather than reimplemented — the point is to test the
    artefact that will actually be applied, so a change to the grants is a
    change these tests see. Only the three names that differ between this
    database and production are substituted.
    """
    sql = _SQL_FILE.read_text()
    sql = sql.replace("marketplace_app", APP_ROLE)
    sql = sql.replace(
        "GRANT CONNECT ON DATABASE marketplace TO",
        "GRANT CONNECT ON DATABASE marketplace_test TO",
    )
    # In production the owner is `marketplace`; here it is whoever the test
    # connects as, which `ALTER DEFAULT PRIVILEGES` needs spelled out.
    sql = sql.replace("FOR ROLE marketplace IN SCHEMA", f"FOR ROLE {_OWNER} IN SCHEMA")
    sql = sql.replace(":'app_password'", f"'{APP_PASSWORD}'")
    return _split_statements(sql)


async def _apply(conn: Any, statements: list[tuple[str, bool]]) -> None:
    """Run the script the way psql would, including ``\\gexec``.

    A ``\\gexec`` statement is executed and each string it returns is then run
    as SQL — which is how the role script creates the role only when it is
    absent. The closing status line is skipped: it exists for a human reading
    psql output.
    """
    for body, is_gexec in statements:
        if not is_gexec and body.upper().startswith("SELECT '"):
            continue
        if is_gexec:
            for generated in (await conn.execute(sa.text(body))).scalars().all():
                await conn.execute(sa.text(generated))
        else:
            await conn.execute(sa.text(body))


@pytest.fixture
async def app_role(db_connection: AsyncConnection, engine: Any) -> Any:
    """Create the restricted role from the shipped script, and drop it after.

    Runs outside the test transaction: `CREATE ROLE` is not transactional in the
    way the rest of this tier assumes, and the role has to exist for a *second*
    connection to authenticate as it.
    """
    admin = create_async_engine(engine.url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await _apply(conn, _script_for_tests())
        yield
    finally:
        async with admin.connect() as conn:
            # DROP OWNED BY also clears the default privileges granted to the
            # role, which a plain DROP ROLE would refuse over.
            await conn.execute(sa.text(f"DROP OWNED BY {APP_ROLE} CASCADE"))
            await conn.execute(sa.text(f"REVOKE ALL ON DATABASE marketplace_test FROM {APP_ROLE}"))
            await conn.execute(sa.text(f"DROP ROLE IF EXISTS {APP_ROLE}"))
        await admin.dispose()


@pytest.fixture
async def as_app(app_role: None, engine: Any) -> Any:
    """Yield a connection authenticated AS the restricted role."""
    url = engine.url.set(username=APP_ROLE, password=APP_PASSWORD)
    restricted = create_async_engine(url, poolclass=NullPool)
    try:
        async with restricted.connect() as conn:
            yield conn
    finally:
        await restricted.dispose()


async def test_the_application_can_do_its_job(as_app: AsyncConnection) -> None:
    """The baseline. Every refusal below is worthless if this fails."""
    # Act
    count = await as_app.scalar(sa.text("SELECT count(*) FROM auth.users"))

    # Assert
    assert count is not None


async def test_the_application_can_write(as_app: AsyncConnection) -> None:
    """Read-only would be a different product, not a safer one."""
    # Act / Assert — rolled back, so nothing persists.
    trans = await as_app.begin()
    await as_app.execute(
        sa.text(
            "INSERT INTO auth.users (id, email, hashed_password, is_active, role) "
            "VALUES (gen_random_uuid(), 'grant-probe@example.com', 'x', true, 'user')"
        )
    )
    await trans.rollback()


async def test_the_application_cannot_drop_a_table(as_app: AsyncConnection) -> None:
    """The refusal that separates "our role" from "the owner's role"."""
    # Act / Assert
    with pytest.raises(ProgrammingError) as excinfo:
        await as_app.execute(sa.text("DROP TABLE auth.users"))

    assert "must be owner" in str(excinfo.value) or "permission denied" in str(excinfo.value)


async def test_the_application_cannot_create_a_table(as_app: AsyncConnection) -> None:
    """No DDL: reshaping the database is a deploy-time act, not a request."""
    # Act / Assert
    with pytest.raises(ProgrammingError) as excinfo:
        await as_app.execute(sa.text("CREATE TABLE auth.smuggled (id int)"))

    assert "permission denied" in str(excinfo.value)


async def test_the_application_cannot_disable_the_audit_trigger(
    as_app: AsyncConnection,
) -> None:
    """Otherwise the append-only guarantee is one `ALTER TABLE` from gone."""
    # Act / Assert
    with pytest.raises(ProgrammingError) as excinfo:
        await as_app.execute(
            sa.text("ALTER TABLE organizations.audit_log DISABLE TRIGGER audit_log_no_rewrite")
        )

    assert "must be owner" in str(excinfo.value) or "permission denied" in str(excinfo.value)


async def test_the_application_cannot_update_the_audit_log_by_grant(
    as_app: AsyncConnection,
) -> None:
    """The point of P2.4 for P1.3: a second layer that does not need the trigger.

    The trigger already refuses this. What this asserts is that the *grant*
    refuses it too — so the guarantee survives the trigger being dropped by
    someone who can drop it, which is precisely the person this role is not.
    """
    # Act / Assert
    with pytest.raises(ProgrammingError) as excinfo:
        await as_app.execute(sa.text("UPDATE organizations.audit_log SET actor_email = 'x'"))

    message = str(excinfo.value)
    # Which layer refused is the whole question, so assert on both sides of it.
    # Postgres checks privileges before it runs the statement, so the grant
    # answers first and the trigger is never reached — verified: SQLSTATE 42501,
    # "permission denied for table audit_log".
    assert "permission denied" in message, "must be refused by the GRANT"
    assert "append-only" not in message, (
        "the trigger answered, which means the grant did not — the second layer is missing"
    )


async def test_the_application_can_still_append_to_the_audit_log(
    as_app: AsyncConnection,
) -> None:
    """Append-only means append: the app writes the trail it cannot edit."""
    # Act / Assert
    trans = await as_app.begin()
    await as_app.execute(
        sa.text(
            "INSERT INTO organizations.audit_log (id, event) "
            "VALUES (gen_random_uuid(), 'GRANT_PROBE')"
        )
    )
    await trans.rollback()


async def test_the_role_is_not_a_superuser(as_app: AsyncConnection) -> None:
    """A superuser bypasses every grant above, silently."""
    # Act
    row = await as_app.execute(
        sa.text(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user"
        )
    )

    # Assert
    assert list(row.one()) == [False, False, False, False]
