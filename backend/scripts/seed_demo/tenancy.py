"""Who the demo is: its account, company and workspace — and the guard around them.

The seed EMPTIES the database before it writes, because the demo's dates move
with the calendar and yesterday's rows would otherwise linger beside today's.
That is only acceptable on a database that holds nothing but the demo, so
before anything is touched this refuses:

* any environment but ``local`` — read from the settings of the process the
  seed runs in, which inside the stack is the api container's own;
* any account but the demo's, and any catalogue card or settlement row outside
  the demo's id ranges — the things only real use creates.

Companies and workspaces are not counted: the migrations themselves create the
platform's first company and workspace, so a freshly migrated database already
holds one of each with nobody in it.

The demo account owns a company marked primary — the platform operator's own —
which is what shows it the internal sections (the labs) without making it a
developer with every administrative screen.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from scripts.seed_demo.catalogue import NM_ID_BASE, REPORT_ID_BASE
from src.core.config import settings
from src.core.security import hash_password
from src.modules.finreports.models import LogisticsTransaction
from src.modules.monitoring.models import ProductCard
from src.modules.organizations.models import MemberRole, Membership, Organization, Subscription
from src.modules.users.models import ROLE_USER, User
from src.modules.workspaces.models import Workspace

#: The demo login. Not a secret: it exists only in a demo database, and it is
#: printed by `make demo` and written in the README so anyone can log in.
DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo-password"  # noqa: S105 — the published demo login, see above
DEMO_ORGANIZATION = "Демо-компания"
DEMO_WORKSPACE = "Демо"

#: Everything the application writes, emptied before a reseed.
_SCHEMAS = ("auth", "organizations", "workspaces", "monitoring", "finreports", "heatmap",
            "ab_tests", "guide")  # fmt: skip
#: Kept: the audit log refuses truncation by design and records this one;
#: the exchange rates are reference data a migration loaded.
_KEEP = frozenset({("organizations", "audit_log"), ("monitoring", "cbr_rate")})


class NotADemoDatabaseError(RuntimeError):
    """The target holds something other than the demo, so it must not be emptied."""


async def _count(session: AsyncSession, condition: ColumnElement[bool]) -> int:
    """How many rows of the table ``condition`` is on satisfy it."""
    return int(await session.scalar(select(func.count()).where(condition)) or 0)


async def real_data(session: AsyncSession) -> dict[str, int]:
    """What the database holds that no seed wrote: cards and settlement rows outside
    the demo's id ranges. Empty when there is none.
    """
    found = {
        "catalogue cards": await _count(session, ProductCard.nm_id < NM_ID_BASE),
        "settlement rows": await _count(session, LogisticsTransaction.report_id < REPORT_ID_BASE),
    }
    return {kind: count for kind, count in found.items() if count}


async def assert_demo_database(session: AsyncSession) -> None:
    """Refuse unless this is a local database holding nothing but the demo.

    Raises:
        NotADemoDatabaseError: Naming what was found.
    """
    if settings.environment != "local":
        raise NotADemoDatabaseError(
            f"ENVIRONMENT={settings.environment}: the demo seed runs only where it is 'local'."
        )
    others = await real_data(session)
    accounts = await _count(session, User.email != DEMO_EMAIL)
    if accounts:
        others = {"accounts": accounts, **others}
    if others:
        listed = ", ".join(f"{count} {kind}" for kind, count in others.items())
        raise NotADemoDatabaseError(
            f"This database holds {listed} that are not the demo's, and the seed "
            "empties every table before it writes. Run it only against the demo "
            "stack (`make demo`), never against one with real data."
        )


async def empty_database(session: AsyncSession) -> None:
    """Truncate every application table but the audit log and the exchange rates.

    The harvested schemas refuse an unannounced TRUNCATE; the seed announces
    itself, and the guard writes the attempt to the audit log.
    """
    tables = (
        await session.execute(
            text("SELECT schemaname, tablename FROM pg_tables WHERE schemaname = ANY(:schemas)"),
            {"schemas": list(_SCHEMAS)},
        )
    ).all()
    targets = sorted(
        f'"{schema}"."{table}"' for schema, table in tables if (schema, table) not in _KEEP
    )
    await session.execute(text("SET LOCAL application_name = 'seed_demo'"))
    await session.execute(text("SET LOCAL app.allow_truncate = 'on'"))
    await session.execute(text(f"TRUNCATE TABLE {', '.join(targets)}"))


async def create_identity(session: AsyncSession) -> uuid.UUID:
    """Create the demo account, its company, subscription and workspace.

    Returns:
        The demo workspace's id.
    """
    now = datetime.now(UTC)
    account = User(
        email=DEMO_EMAIL,
        hashed_password=await asyncio.to_thread(hash_password, DEMO_PASSWORD),
        is_active=True,
        role=ROLE_USER,
        email_confirmed_at=now,
    )
    company = Organization(name=DEMO_ORGANIZATION, is_primary=True)
    session.add_all([account, company])
    await session.flush()
    session.add_all(
        [
            Membership(organization_id=company.id, user_id=account.id, role=MemberRole.OWNER.value),
            Subscription(
                organization_id=company.id,
                started_at=now,
                expires_at=now + timedelta(days=365),
                grace_days=settings.subscription_grace_days,
            ),
        ]
    )
    workspace = Workspace(name=DEMO_WORKSPACE, is_primary=True, organization_id=company.id)
    session.add(workspace)
    await session.flush()
    return workspace.id
