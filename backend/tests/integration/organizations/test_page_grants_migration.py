"""«Сводка» and «Тепловая карта» go exactly to who could open them (``d7f1a3c95e24``).

Before this migration «Сводка» opened on «Мониторинг» AND P&L, and «Тепловая
карта» on «Мониторинг». The migration turns both into grants of their own, and
the property that matters is that nobody's reach to a page changes on the
deploy — above all, that a manager whose owner closed P&L to them does not find
the кабинет's revenue on «Сводка» the morning after.

Nothing below asserts on the SQL: each case seeds a membership or invitation the
way the previous revision stored it, runs the one upgrade, and reads the list
back.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.pool import NullPool

from alembic import command
from src.core.config import settings
from tests.integration.conftest import _dsn

#: Its own database: the migration is replayed from the revision before it,
#: which the shared integration database must never be dragged back to.
_SCRATCH_DB_NAME = "marketplace_page_grants_check"

_BEFORE = "e8b3d5a1c962"
_THE_GRANTS = "d7f1a3c95e24"

_OLD_ALL = ["monitoring", "finreports", "ab_tests", "advertising"]


def _sync_dsn(database: str) -> str:
    """Return the psycopg (synchronous) DSN Alembic drives migrations through."""
    return _dsn(database).replace("postgresql+asyncpg", "postgresql+psycopg")


def _admin_engine() -> sa.Engine:
    """An AUTOCOMMIT engine on ``postgres`` for CREATE/DROP DATABASE."""
    return sa.create_engine(_sync_dsn("postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT")


def _migrate_scratch(direction: str, revision: str) -> None:
    """Run one upgrade or downgrade against the scratch database, then restore the settings.

    ``alembic/env.py`` reads the URL from the settings singleton, so the scratch
    copy is reached by mutating it — and leaving it mutated would send the rest
    of the tier to a database that is about to be dropped.
    """
    original_db = settings.postgres_db
    settings.postgres_db = _SCRATCH_DB_NAME
    try:
        getattr(command, direction)(Config("alembic.ini"), revision)
    finally:
        settings.postgres_db = original_db


@pytest.fixture
def scratch(postgres_ready: bool) -> Iterator[sa.Engine]:
    """A scratch database at the revision just before the page grants.

    Yields:
        An engine on it.
    """
    admin = _admin_engine()
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB_NAME}" WITH (FORCE)'))
        conn.execute(sa.text(f'CREATE DATABASE "{_SCRATCH_DB_NAME}"'))
    admin.dispose()

    engine = sa.create_engine(_sync_dsn(_SCRATCH_DB_NAME), poolclass=NullPool)
    try:
        _migrate_scratch("upgrade", _BEFORE)
        yield engine
    finally:
        engine.dispose()
        admin = _admin_engine()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB_NAME}" WITH (FORCE)'))
        admin.dispose()


def _organization(conn: sa.Connection) -> uuid.UUID:
    """Insert one ordinary organisation and return its id."""
    org_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO organizations.organizations (id, name, is_primary) "
            "VALUES (:id, 'Клиент', false)"
        ).bindparams(id=org_id)
    )
    return org_id


def _manager(conn: sa.Connection, org_id: uuid.UUID, modules: list[str]) -> uuid.UUID:
    """Insert a user and their manager membership holding ``modules``; return the membership id."""
    user_id, membership_id = uuid.uuid4(), uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO auth.users (id, email, hashed_password, is_active, role) "
            "VALUES (:id, :email, 'x', true, 'user')"
        ).bindparams(id=user_id, email=f"{user_id.hex}@example.com")
    )
    conn.execute(
        sa.text(
            "INSERT INTO organizations.memberships "
            "(id, organization_id, user_id, role, access_level, modules) "
            "VALUES (:id, :org, :user, 'manager', 'read_write', CAST(:modules AS jsonb))"
        ).bindparams(id=membership_id, org=org_id, user=user_id, modules=json.dumps(modules))
    )
    return membership_id


def _invitation(conn: sa.Connection, org_id: uuid.UUID, modules: list[str]) -> uuid.UUID:
    """Insert a pending manager invitation carrying ``modules``; return its id."""
    invitation_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO organizations.invitations "
            "(id, organization_id, token_hash, role, access_level, modules, expires_at) "
            "VALUES (:id, :org, :hash, 'manager', 'read_write', CAST(:modules AS jsonb), :exp)"
        ).bindparams(
            id=invitation_id,
            org=org_id,
            hash=invitation_id.hex * 2,
            modules=json.dumps(modules),
            exp=datetime.now(UTC) + timedelta(days=7),
        )
    )
    return invitation_id


def _modules(conn: sa.Connection, table: str, row_id: uuid.UUID) -> set[str]:
    """Read one row's module list back as a set."""
    statement = {
        "memberships": "SELECT modules FROM organizations.memberships WHERE id = :id",
        "invitations": "SELECT modules FROM organizations.invitations WHERE id = :id",
    }[table]
    return set(conn.execute(sa.text(statement).bindparams(id=row_id)).scalar_one())


@pytest.mark.parametrize(
    ("before", "gained"),
    [
        (_OLD_ALL, {"summary", "heatmap"}),
        (["monitoring", "finreports"], {"summary", "heatmap"}),
        (["monitoring"], {"heatmap"}),
        (["finreports", "advertising"], set()),
        ([], set()),
    ],
    ids=["everything", "both-halves", "monitoring-only", "pnl-without-monitoring", "nothing"],
)
@pytest.mark.parametrize("table", ["memberships", "invitations"])
def test_each_page_goes_to_exactly_who_could_open_it(
    scratch: sa.Engine, table: str, before: list[str], gained: set[str]
) -> None:
    """«Сводка» where both halves were held, «Тепловая карта» where «Мониторинг» was."""
    with scratch.begin() as conn:
        org_id = _organization(conn)
        seed = _manager if table == "memberships" else _invitation
        row_id = seed(conn, org_id, before)

    _migrate_scratch("upgrade", _THE_GRANTS)

    with scratch.connect() as conn:
        assert _modules(conn, table, row_id) == set(before) | gained


def test_a_manager_without_pnl_does_not_gain_the_summary(scratch: sa.Engine) -> None:
    """The case the rule exists for: P&L closed by the owner stays closed on «Сводка»."""
    with scratch.begin() as conn:
        row_id = _manager(conn, _organization(conn), ["monitoring", "ab_tests", "advertising"])

    _migrate_scratch("upgrade", _THE_GRANTS)

    with scratch.connect() as conn:
        assert "summary" not in _modules(conn, "memberships", row_id)


def test_a_new_membership_gets_every_page_by_default(scratch: sa.Engine) -> None:
    """The column default names all six pages, as the model's does."""
    _migrate_scratch("upgrade", _THE_GRANTS)
    with scratch.begin() as conn:
        org_id = _organization(conn)
        user_id = uuid.uuid4()
        conn.execute(
            sa.text(
                "INSERT INTO auth.users (id, email, hashed_password, is_active, role) "
                "VALUES (:id, 'fresh@example.com', 'x', true, 'user')"
            ).bindparams(id=user_id)
        )
        membership_id = conn.execute(
            sa.text(
                "INSERT INTO organizations.memberships (id, organization_id, user_id, role) "
                "VALUES (:id, :org, :user, 'manager') RETURNING id"
            ).bindparams(id=uuid.uuid4(), org=org_id, user=user_id)
        ).scalar_one()

    with scratch.connect() as conn:
        assert _modules(conn, "memberships", membership_id) == {*_OLD_ALL, "summary", "heatmap"}


def test_the_downgrade_puts_every_list_back(scratch: sa.Engine) -> None:
    """Both keys come out again and nothing else is touched."""
    with scratch.begin() as conn:
        row_id = _manager(conn, _organization(conn), ["monitoring", "finreports"])
    _migrate_scratch("upgrade", _THE_GRANTS)

    _migrate_scratch("downgrade", _BEFORE)

    with scratch.connect() as conn:
        assert _modules(conn, "memberships", row_id) == {"monitoring", "finreports"}
