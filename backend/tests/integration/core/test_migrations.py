"""Integration test for Alembic migration integrity.

The rest of the integration tier builds its schema straight from the models
(``Base.metadata.create_all``) because that is fast and it is the models the
repositories are written against. That shortcut is only safe if *something*
proves the migrations still produce the same schema — otherwise a model change
merged without its migration passes every test and fails on deploy, which is
exactly the moment it is most expensive.

So this module replays the full migration history onto a scratch database and
asks Alembic's autogenerate whether anything is still missing. An empty diff is
the assertion.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.pool import NullPool

from alembic import command
from src.core.config import settings
from src.core.database import Base
from tests.integration.conftest import SCHEMAS, _dsn

#: Scratch database used only here, so replaying migrations can never disturb
#: the shared ``marketplace_test`` schema the other integration tests use.
MIGRATION_DB_NAME = "marketplace_migration_check"

#: Schemas Alembic owns; anything else in the cluster is out of scope.
_OWNED_SCHEMAS = frozenset(SCHEMAS)

#: Indexes that exist in the database by migration only, because SQLAlchemy's
#: declarative models cannot express them and autogenerate cannot reflect them
#: back — so every diff would propose dropping them. Each one is asserted to
#: actually exist by its own test below, so the exemption cannot hide a loss.
MIGRATION_ONLY_INDEXES: frozenset[str] = frozenset({"uq_users_email_lower"})


def _significant(diff: list[object]) -> list[object]:
    """Drop the known-unreflectable entries from an autogenerate diff.

    Args:
        diff: Raw output of :func:`alembic.autogenerate.compare_metadata`.

    Returns:
        Only the entries that represent real, actionable drift.
    """
    significant: list[object] = []
    for entry in diff:
        if (
            isinstance(entry, tuple)
            and len(entry) == 2
            and entry[0] == "remove_index"
            and getattr(entry[1], "name", None) in MIGRATION_ONLY_INDEXES
        ):
            continue
        significant.append(entry)
    return significant


def _sync_dsn(database: str) -> str:
    """Return the psycopg (synchronous) DSN Alembic drives migrations through."""
    return _dsn(database).replace("postgresql+asyncpg", "postgresql+psycopg")


@pytest.fixture(scope="module")
def migrated_database(postgres_ready: bool) -> str:
    """Create a scratch database and run ``alembic upgrade head`` on it.

    Returns:
        The synchronous DSN of the freshly migrated database.
    """
    admin = sa.create_engine(
        _sync_dsn("postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}" WITH (FORCE)'))
        conn.execute(sa.text(f'CREATE DATABASE "{MIGRATION_DB_NAME}"'))
    admin.dispose()

    # alembic/env.py reads the URL from the settings singleton, so redirecting
    # the database name there is what points the migration at the scratch copy.
    original_db = settings.postgres_db
    settings.postgres_db = MIGRATION_DB_NAME
    try:
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        yield _sync_dsn(MIGRATION_DB_NAME)
    finally:
        settings.postgres_db = original_db
        admin = sa.create_engine(
            _sync_dsn("postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT"
        )
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}" WITH (FORCE)'))
        admin.dispose()


def test_there_is_exactly_one_migration_head() -> None:
    """Two heads mean two branches merged without a merge revision.

    ``alembic upgrade head`` then fails on deploy with an ambiguity error — a
    problem worth catching in CI, not at 3 a.m. on the VPS.
    """
    script = ScriptDirectory.from_config(Config("alembic.ini"))

    assert len(script.get_heads()) == 1


def test_migrations_apply_cleanly_from_an_empty_database(migrated_database: str) -> None:
    """The full history replays onto a blank database without error.

    A fresh environment (a new staging box, a restored backup, a contributor's
    laptop) only ever takes this path.
    """
    engine = sa.create_engine(migrated_database, poolclass=NullPool)
    with engine.connect() as conn:
        present = {
            row[0]
            for row in conn.execute(sa.text("SELECT schema_name FROM information_schema.schemata"))
        }
    engine.dispose()

    assert _OWNED_SCHEMAS.issubset(present)


def test_the_audit_log_guard_survives_the_migrated_path(migrated_database: str) -> None:
    """The append-only trigger must exist however the database was built.

    It is declared twice on purpose — as ``after_create`` DDL on the model, for
    ``create_all``, and in the migration, for production. The drift guard below
    compares tables and columns and would not notice a trigger present in one
    path and missing from the other, which is the divergence that would ship an
    unprotected audit log to the only database that matters (P1.3).
    """
    engine = sa.create_engine(migrated_database, poolclass=NullPool)
    with engine.connect() as conn:
        # pg_trigger, not information_schema.triggers: the standard view has no
        # notion of a TRUNCATE trigger and silently omits it, which made the
        # first version of this test fail against a database that was correct.
        triggers = {
            row[0]
            for row in conn.execute(
                sa.text(
                    """
                    SELECT t.tgname
                    FROM pg_trigger t
                    JOIN pg_class c ON c.oid = t.tgrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'organizations'
                      AND c.relname = 'audit_log'
                      AND NOT t.tgisinternal
                    """
                )
            )
        }
    engine.dispose()

    assert "audit_log_no_rewrite" in triggers
    assert "audit_log_no_truncate" in triggers


def test_the_migrated_schema_matches_the_models(migrated_database: str) -> None:
    """Autogenerate finds nothing left to do — no missing migration.

    This is the drift guard: change a model, forget the migration, and this test
    reports the exact tables/columns Alembic would still need to create.
    """
    engine = sa.create_engine(migrated_database, poolclass=NullPool)
    with engine.connect() as conn:
        context = MigrationContext.configure(
            conn,
            opts={
                "include_schemas": True,
                "compare_type": True,
                # Restrict the diff to schemas this application owns, exactly as
                # alembic/env.py does; without it autogenerate would propose
                # dropping every unrelated table in the cluster.
                "include_name": lambda name, type_, parent: (
                    name in _OWNED_SCHEMAS if type_ == "schema" else True
                ),
            },
        )
        diff = _significant(compare_metadata(context, Base.metadata))
    engine.dispose()

    assert diff == [], (
        "The models and the migrations disagree. Generate the missing revision "
        f"with `alembic revision --autogenerate`. Outstanding changes: {diff}"
    )


def test_emails_are_unique_case_insensitively_in_the_database(
    migrated_database: str,
) -> None:
    """The ``lower(email)`` unique index is present and actually enforced.

    The service lowercases every email, but this index is what makes the
    invariant hold for any future code path that forgets to — two accounts
    differing only in case would otherwise both exist, and one of them could
    never log in. It is exempt from the drift diff above, so it needs its own
    positive assertion.
    """
    engine = sa.create_engine(migrated_database, poolclass=NullPool)
    with engine.connect() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO auth.users (id, email, hashed_password, is_active, role) "
                "VALUES (gen_random_uuid(), 'dup@example.com', 'x', true, 'user')"
            )
        )
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO auth.users (id, email, hashed_password, is_active, role) "
                    "VALUES (gen_random_uuid(), 'DUP@Example.com', 'x', true, 'user')"
                )
            )
        conn.rollback()
    engine.dispose()


def test_every_table_lives_in_an_owned_schema(migrated_database: str) -> None:
    """No application table may land in ``public``.

    The multi-schema layout is what keeps module boundaries visible in the
    database itself; a stray ``public`` table is a module leaking out of its box.
    """
    engine = sa.create_engine(migrated_database, poolclass=NullPool)
    with engine.connect() as conn:
        public_tables = [
            row[0]
            for row in conn.execute(
                sa.text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    "AND tablename <> 'alembic_version'"
                )
            )
        ]
    engine.dispose()

    assert public_tables == []
