"""Tenancy that survives a forgotten `WHERE` (register P2.5).

Application scoping already works and is tested elsewhere. Its weakness is not a
bug — it is that the guarantee is re-made by every query, so it holds only until
somebody writes one that forgets, and that failure looks exactly like working
code. These cases assert the property that does not depend on remembering: a
`SELECT` with **no tenant predicate at all** still cannot see another
workspace's rows.

That is why the queries below are deliberately naive. A test that scoped its own
SQL would pass with the policies dropped, which is the one thing it must not do.

Two dependencies are load-bearing and both are asserted rather than assumed:

* RLS does not apply to a table's **owner**. The application is the owner today,
  so these tests connect as the restricted role from
  `least_privilege_role.sql` — the same role P2.4 introduces. Until that role is
  in use in production, the policies are inert there, and `test_the_owner_still
  _crosses_workspaces` pins that as intended behaviour rather than an oversight:
  it is what keeps migrations and the cross-workspace Celery harvests working.
* A missing tenant **raises**. `current_setting` is read without `missing_ok`, so
  a query that arrives with no workspace bound errors instead of quietly
  returning nothing. An empty result reads as "this customer has no data" and
  gets "fixed" by deleting the scoping; an error cannot be misread.
"""

from __future__ import annotations

import pathlib
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from tests.integration.core.test_least_privilege_role import (
    APP_PASSWORD,
    APP_ROLE,
    _split_statements,
)
from tests.integration.core.test_least_privilege_role import (
    _script_for_tests as _role_script,
)

pytestmark = pytest.mark.integration

_RLS_FILE = (
    pathlib.Path(__file__).resolve().parents[3] / "scripts" / "sql" / "row_level_security.sql"
)

MINE = uuid.UUID("019f657a-0000-7000-8000-00000000aaaa")
THEIRS = uuid.UUID("019f657a-0000-7000-8000-00000000bbbb")

#: Fixed ids rather than hashed ones — `hash()` is salted per process, so a
#: derived id would differ between the run that inserts and any run that cleans
#: up after a crash.
_PROBE_NM_ID = {MINE: 990000001, THEIRS: 990000002}


def _rls_statements() -> list[str]:
    """Return the shipped policy script's statements.

    Read rather than restated, so a change to the policies is a change these
    tests see.
    """
    return [
        s
        for s in _split_statements(_RLS_FILE.read_text())
        if not s.upper().startswith("SELECT")  # the closing report, for a human
    ]


@pytest.fixture
async def isolated(engine: Any) -> Any:
    """Install the role and the policies, seed two tenants, and clean up.

    Everything runs on its own AUTOCOMMIT connection: `CREATE ROLE` and
    `ALTER TABLE` are not things to leave inside the tier's shared transaction,
    and the restricted role has to exist for a second connection to
    authenticate as it.
    """
    admin = create_async_engine(engine.url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            for statement in _role_script():
                if statement.upper().startswith("SELECT '"):
                    continue
                await conn.execute(sa.text(statement))
            for statement in _rls_statements():
                await conn.execute(sa.text(statement))
            # One product card in each of two workspaces. `product_card` is the
            # table every monitoring read starts from, so it is the one whose
            # leak would be widest.
            for workspace in (MINE, THEIRS):
                await conn.execute(
                    sa.text(
                        "INSERT INTO monitoring.product_card "
                        "(nm_id, workspace_id, vendor_code, title) "
                        "VALUES (:nm_id, :ws, :code, :title)"
                    ),
                    {
                        "nm_id": _PROBE_NM_ID[workspace],
                        "ws": workspace,
                        "code": "RLS-PROBE",
                        "title": "RLS probe",
                    },
                )
        yield
    finally:
        async with admin.connect() as conn:
            await conn.execute(
                sa.text("DELETE FROM monitoring.product_card WHERE vendor_code = 'RLS-PROBE'")
            )
            # Turn the policies back off so the rest of the tier is unaffected.
            for table in ("monitoring.product_card",):
                await conn.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
            await conn.execute(sa.text(f"DROP OWNED BY {APP_ROLE} CASCADE"))
            await conn.execute(sa.text(f"REVOKE ALL ON DATABASE marketplace_test FROM {APP_ROLE}"))
            await conn.execute(sa.text(f"DROP ROLE IF EXISTS {APP_ROLE}"))
        await admin.dispose()


@pytest.fixture
async def as_app(isolated: None, engine: Any) -> Any:
    """A connection authenticated as the restricted application role."""
    url = engine.url.set(username=APP_ROLE, password=APP_PASSWORD)
    restricted = create_async_engine(url, poolclass=NullPool)
    try:
        async with restricted.connect() as conn:
            yield conn
    finally:
        await restricted.dispose()


async def _bind(conn: AsyncConnection, workspace_id: uuid.UUID) -> None:
    """Bind a workspace the way `src.core.tenancy` does."""
    await conn.execute(
        sa.text("SELECT set_config('app.workspace_id', :value, true)"),
        {"value": str(workspace_id)},
    )


async def test_an_unscoped_select_sees_only_the_bound_workspace(
    as_app: AsyncConnection,
) -> None:
    """The whole point: no `WHERE`, and still no other tenant's rows."""
    # Arrange
    await as_app.begin()
    await _bind(as_app, MINE)

    # Act — deliberately naive. Scoping this query would test nothing.
    rows = (
        (
            await as_app.execute(
                sa.text(
                    "SELECT workspace_id FROM monitoring.product_card "
                    "WHERE vendor_code = 'RLS-PROBE'"
                )
            )
        )
        .scalars()
        .all()
    )

    # Assert
    assert set(rows) == {MINE}


async def test_the_other_tenants_row_is_invisible_even_when_named(
    as_app: AsyncConnection,
) -> None:
    """Asking for it by id is the query a leak actually looks like."""
    # Arrange
    await as_app.begin()
    await _bind(as_app, MINE)

    # Act
    found = await as_app.scalar(
        sa.text("SELECT count(*) FROM monitoring.product_card WHERE workspace_id = :ws"),
        {"ws": THEIRS},
    )

    # Assert
    assert found == 0


async def test_a_query_with_no_workspace_bound_raises(as_app: AsyncConnection) -> None:
    """Fail closed AND loudly — an empty result would get "fixed" by someone."""
    # Arrange
    await as_app.begin()

    # Act / Assert
    with pytest.raises(DBAPIError) as excinfo:
        await as_app.execute(sa.text("SELECT count(*) FROM monitoring.product_card"))

    assert "app.workspace_id" in str(excinfo.value)


async def test_the_app_cannot_write_into_another_workspace(
    as_app: AsyncConnection,
) -> None:
    """A leak has two directions; WITH CHECK covers the one people forget."""
    # Arrange
    await as_app.begin()
    await _bind(as_app, MINE)

    # Act / Assert
    with pytest.raises(ProgrammingError) as excinfo:
        await as_app.execute(
            sa.text(
                "INSERT INTO monitoring.product_card "
                "(nm_id, workspace_id, vendor_code, title) "
                "VALUES (424242, :ws, 'RLS-PROBE', 'RLS probe')"
            ),
            {"ws": THEIRS},
        )

    assert "row-level security" in str(excinfo.value)


async def test_the_owner_still_crosses_workspaces(
    isolated: None, db_connection: AsyncConnection
) -> None:
    """Intended, and the reason the policies are safe to install early.

    Migrations and the nightly harvests legitimately span every workspace, and
    they connect as the owner — for whom RLS does not apply. If this ever starts
    failing, the harvests stop, so it is pinned as behaviour rather than left as
    an assumption.
    """
    # Act — the tier's normal connection is the owner, and binds nothing.
    rows = (
        (
            await db_connection.execute(
                sa.text(
                    "SELECT workspace_id FROM monitoring.product_card "
                    "WHERE vendor_code = 'RLS-PROBE'"
                )
            )
        )
        .scalars()
        .all()
    )

    # Assert
    assert set(rows) == {MINE, THEIRS}
