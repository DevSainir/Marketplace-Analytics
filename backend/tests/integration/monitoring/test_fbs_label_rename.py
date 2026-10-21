"""Renaming an FBS warehouse label takes its history with it (``c7e4a1d90b62``).

The label is not decoration: ``stock_snapshot.warehouse_name`` is part of that
table's primary key and ``warehouse_mark.warehouse_name`` is how a «Отгрузить»
mark finds its warehouse. A rename that touches only the directory row leaves
every past snapshot filed under a name nothing points at any more — the column
appears to start from scratch and the marks silently detach.

Nothing below asserts on the SQL. What is pinned is the property that makes the
rename safe to run at all: after it, the same rows are still reachable under
the new name, and none are left behind under the old one.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.pool import NullPool

from alembic import command
from src.core.config import settings
from tests.integration.conftest import _dsn

#: Its own database: the rename is replayed from an earlier revision, which the
#: shared integration database must never be dragged back to.
_RENAME_DB_NAME = "marketplace_fbs_rename_check"

_BEFORE_THE_RENAME = "b4f1e7c92d05"
_THE_RENAME = "c7e4a1d90b62"

_OLD_LABEL = "Москва (Белая дача) (FBS)"
_NEW_LABEL = "Белая дача - Москва (FBS)"
_WAREHOUSE_ID = 9990254

#: Vnukovo needs no seeding here — ``b4f1e7c92d05`` writes it, under the label
#: it had been harvesting under. It is in every assertion below because a
#: rename that misses the row a previous migration seeded is the same failure
#: as one that misses a row discovery wrote.
_SEEDED_NEW_LABEL = "Внуково - Москва (FBS)"

#: An FBO warehouse in the same table, to prove the rename is a rename and not
#: a broad UPDATE that catches whatever else is filed nearby.
_UNTOUCHED_LABEL = "Коледино"


def _sync_dsn(database: str) -> str:
    """Return the psycopg (synchronous) DSN Alembic drives migrations through."""
    return _dsn(database).replace("postgresql+asyncpg", "postgresql+psycopg")


def _admin_engine() -> sa.Engine:
    """An AUTOCOMMIT engine on ``postgres`` for CREATE/DROP DATABASE."""
    return sa.create_engine(_sync_dsn("postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT")


def _upgrade_scratch_to(revision: str) -> None:
    """Run one upgrade against the scratch database and put the settings back.

    ``alembic/env.py`` reads the URL from the settings singleton, so pointing a
    migration at the scratch copy means mutating it — and leaving it mutated
    would send the rest of the tier's queries to a database that is about to be
    dropped.
    """
    original_db = settings.postgres_db
    settings.postgres_db = _RENAME_DB_NAME
    try:
        command.upgrade(Config("alembic.ini"), revision)
    finally:
        settings.postgres_db = original_db


@pytest.fixture
def database_before_the_rename(postgres_ready: bool) -> Iterator[str]:
    """A scratch database migrated to the revision just before the rename.

    Yields:
        The synchronous DSN of a database holding the pre-rename schema.
    """
    admin = _admin_engine()
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{_RENAME_DB_NAME}" WITH (FORCE)'))
        conn.execute(sa.text(f'CREATE DATABASE "{_RENAME_DB_NAME}"'))
    admin.dispose()

    try:
        _upgrade_scratch_to(_BEFORE_THE_RENAME)
        yield _sync_dsn(_RENAME_DB_NAME)
    finally:
        admin = _admin_engine()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{_RENAME_DB_NAME}" WITH (FORCE)'))
        admin.dispose()


def _seed_a_warehouse_with_history(dsn: str) -> None:
    """Write a directory row, two days of stock and a mark, all under the old label."""
    engine = sa.create_engine(dsn, poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO monitoring.fbs_warehouse (warehouse_id, label, wb_name) "
                "VALUES (:id, :label, 'Иван - Москва (Белая дача) НЕ УДАЛЯТЬ!!!')"
            ).bindparams(id=_WAREHOUSE_ID, label=_OLD_LABEL)
        )
        for stat_date, quantity in ((date(2026, 8, 20), 200), (date(2026, 8, 21), 180)):
            for label in (_OLD_LABEL, _UNTOUCHED_LABEL):
                conn.execute(
                    sa.text(
                        "INSERT INTO monitoring.stock_snapshot "
                        "(stat_date, nm_id, warehouse_name, chrt_id, region_name, quantity, "
                        " in_way_to_client, in_way_from_client) "
                        "VALUES (:d, 10101, :w, 965033858, 'FBS', :q, 0, 0)"
                    ).bindparams(d=stat_date, w=label, q=quantity)
                )
        conn.execute(
            sa.text(
                "INSERT INTO monitoring.warehouse_mark (nm_id, warehouse_name) VALUES (10101, :w)"
            ).bindparams(w=_OLD_LABEL)
        )
    engine.dispose()


def _labels_in(dsn: str) -> dict[str, list[str]]:
    """Every label currently stored, per table."""
    engine = sa.create_engine(dsn, poolclass=NullPool)
    with engine.connect() as conn:
        directory = list(
            conn.scalars(
                sa.text("SELECT label FROM monitoring.fbs_warehouse ORDER BY warehouse_id")
            )
        )
        stock = list(
            conn.scalars(
                sa.text("SELECT warehouse_name FROM monitoring.stock_snapshot ORDER BY stat_date")
            )
        )
        marks = list(conn.scalars(sa.text("SELECT warehouse_name FROM monitoring.warehouse_mark")))
    engine.dispose()
    return {"directory": directory, "stock": stock, "marks": marks}


def test_a_renamed_warehouse_keeps_its_stock_history_and_its_marks(
    database_before_the_rename: str,
) -> None:
    """Both snapshot days and the «Отгрузить» mark move to the new label.

    This is the whole reason the rename is a migration rather than a config
    edit: the label is a primary-key value, so anything left behind under the
    old text is history the warehouse can no longer be shown to have.
    """
    _seed_a_warehouse_with_history(database_before_the_rename)

    _upgrade_scratch_to(_THE_RENAME)
    stored = _labels_in(database_before_the_rename)

    assert stored["directory"] == [_SEEDED_NEW_LABEL, _NEW_LABEL]
    assert stored["stock"].count(_NEW_LABEL) == 2
    assert stored["marks"] == [_NEW_LABEL]


def test_the_rename_leaves_every_other_warehouse_alone(
    database_before_the_rename: str,
) -> None:
    """An FBO warehouse's rows keep their name.

    The stock rows can only be matched on the text they carry, so the statement
    that moves them is one careless `LIKE` away from renaming the WB warehouses
    filed in the same table.
    """
    _seed_a_warehouse_with_history(database_before_the_rename)

    _upgrade_scratch_to(_THE_RENAME)
    stored = _labels_in(database_before_the_rename)

    assert stored["stock"].count(_UNTOUCHED_LABEL) == 2
    assert _OLD_LABEL not in stored["stock"]
