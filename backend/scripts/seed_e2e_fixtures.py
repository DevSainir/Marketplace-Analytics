"""Provision the offline fixtures the end-to-end tier needs, in one run.

The browser tier drives a REAL stack, so it needs three things to exist before
Playwright opens a page — and none of them are supplied by the schema, the
migrations, or ``seed/monitoring_seed.sql.gz``:

1. **An account it can log in as.** ``dump_seed.sh`` deliberately never dumps
   the ``auth`` schema (dev credentials must not travel between hosts), and the
   registration form is invite-gated, so a fresh database has nobody in it.
2. **At least two workspaces.** Every data request carries ``X-Workspace-Id``,
   and the header is rejected unless the workspace row exists. Two, not one, so
   the "switching workspace re-scopes every request" journey has somewhere to
   switch to instead of skipping itself.
3. **SKUs the account can actually see.** This is the subtle one. The committed
   seed dump predates multi-tenancy: its ``COPY monitoring.product_card`` names
   only ``(nm_id, vendor_code, title, synced_at)``. Loading it leaves every
   card with ``workspace_id IS NULL``, and ``workspace_sku_select()`` filters
   those out of every query — so the catalogue is present in the database and
   invisible to the entire application. The SKU-search journey then finds
   nothing, for a reason no error message would explain.

Unlike ``seed_workspace.py`` / ``seed_harvest.py`` this script is **fully
offline**: it touches no WildBerries surface, needs no API token, and finishes
in well under a second. That is what makes it usable from CI.

Every step is idempotent — an existing account keeps its id (its password is
reset to the expected one), existing workspaces are reused, and only *unclaimed*
cards are adopted. Re-running is the intended way to repair a half-seeded stack.

Run from the ``backend`` directory (``.env`` populated, migrations applied)::

    python -m scripts.seed_e2e_fixtures
    python -m scripts.seed_e2e_fixtures --email qa@example.com --password s3cret
    docker compose exec -T api python -m scripts.seed_e2e_fixtures
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import AsyncSessionLocal, engine
from src.core.security import hash_password
from src.modules.monitoring.models import ProductCard
from src.modules.users.models import ROLE_DEV, User
from src.modules.workspaces.models import Workspace

#: Credentials the Playwright fixtures default to (tests/end-to-end/fixtures/app.js).
#: Not a secret: this account exists only inside a throwaway test stack, and the
#: value has to be known to both sides or the browser tier cannot log in. Never
#: run this script against an environment holding real data.
DEFAULT_EMAIL = "dev-preview@example.com"
DEFAULT_PASSWORD = "dev-preview-password"  # noqa: S105 — test-stack fixture, see above

#: Workspace names created when the database has fewer than two. The first one
#: adopts the seeded catalogue; the second exists purely so the workspace-switch
#: journey has a target.
DEFAULT_WORKSPACE_NAMES: tuple[str, str] = ("E2E Primary", "E2E Secondary")


@dataclass(frozen=True)
class SeedReport:
    """What one run changed, for the log line CI operators read.

    Attributes:
        email: The account the tier will log in as.
        account_created: ``True`` when the user row did not exist before.
        workspaces: Names of the workspaces present after the run, oldest first.
        cards_claimed: Product cards adopted out of ``workspace_id IS NULL``.
        cards_visible: Cards the primary workspace can see after the run.
    """

    email: str
    account_created: bool
    workspaces: list[str]
    cards_claimed: int
    cards_visible: int


async def _ensure_account(session: AsyncSession, *, email: str, password: str) -> bool:
    """Create the end-to-end account, or reset its password if it exists.

    The password is rewritten on every run on purpose: a stack reseeded from a
    dump of unknown provenance may carry an account with this email and a
    different digest, which would fail the login journey with a message
    indistinguishable from a genuine auth regression.

    Args:
        session: Open async session (the caller owns the transaction).
        email: Login email, expected already lowercase.
        password: Plaintext password to store as a bcrypt digest.

    Returns:
        ``True`` when a new row was inserted, ``False`` when one was updated.
    """
    digest = await asyncio.to_thread(hash_password, password)
    existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        existing.hashed_password = digest
        existing.is_active = True
        # The tier exercises the workspace admin panel, which is dev-gated.
        existing.role = ROLE_DEV
        return False
    session.add(User(email=email, hashed_password=digest, is_active=True, role=ROLE_DEV))
    return True


async def _ensure_workspaces(session: AsyncSession) -> list[Workspace]:
    """Guarantee at least two workspaces exist, returning them oldest first.

    Args:
        session: Open async session (the caller owns the transaction).

    Returns:
        Every workspace after the run, ordered by creation so the "primary" one
        is stable across runs.
    """
    stmt = select(Workspace).order_by(Workspace.created_at, Workspace.id)
    existing = list((await session.execute(stmt)).scalars().all())
    taken = {workspace.name for workspace in existing}
    for name in DEFAULT_WORKSPACE_NAMES[len(existing) :]:
        if name in taken:
            continue
        workspace = Workspace(name=name, is_primary=not existing)
        session.add(workspace)
        existing.append(workspace)
    await session.flush()
    return existing


async def _claim_unowned_cards(session: AsyncSession, workspace_id: uuid.UUID) -> int:
    """Adopt every ``workspace_id IS NULL`` product card into one workspace.

    Only unclaimed rows are touched, so a card already owned by a workspace is
    never re-tenanted — that would silently move real harvested data between
    tenants on a stack where this script is run by accident.

    Args:
        session: Open async session (the caller owns the transaction).
        workspace_id: The workspace adopting the orphaned catalogue.

    Returns:
        The number of cards claimed.
    """
    # `returning` rather than `rowcount`: the async Result protocol does not
    # expose a row count, and counting the returned keys is exact either way.
    result = await session.execute(
        update(ProductCard)
        .where(ProductCard.workspace_id.is_(None))
        .values(workspace_id=workspace_id)
        .returning(ProductCard.nm_id)
    )
    return len(result.scalars().all())


async def _count_visible_cards(session: AsyncSession, workspace_id: uuid.UUID) -> int:
    """Count the cards a workspace can see (what the SKU search will find)."""
    stmt = (
        select(func.count())
        .select_from(ProductCard)
        .where(ProductCard.workspace_id == workspace_id)
    )
    return int(await session.scalar(stmt) or 0)


async def seed(*, email: str, password: str) -> SeedReport:
    """Provision the account, the workspaces, and the catalogue ownership.

    One transaction: a half-applied seed (an account with no visible SKUs) is
    the exact state that makes the browser tier fail confusingly, so it is
    better to apply nothing at all.

    Args:
        email: Login email for the end-to-end account.
        password: Plaintext password for it.

    Returns:
        A :class:`SeedReport` describing what changed.
    """
    async with AsyncSessionLocal() as session:
        created = await _ensure_account(session, email=email.strip().lower(), password=password)
        workspaces = await _ensure_workspaces(session)
        primary = workspaces[0]
        claimed = await _claim_unowned_cards(session, primary.id)
        visible = await _count_visible_cards(session, primary.id)
        await session.commit()

    return SeedReport(
        email=email,
        account_created=created,
        workspaces=[workspace.name for workspace in workspaces],
        cards_claimed=claimed,
        cards_visible=visible,
    )


def _parse_args() -> argparse.Namespace:
    """Parse the command-line options."""
    parser = argparse.ArgumentParser(
        description="Seed the offline fixtures the end-to-end tier needs (account, "
        "workspaces, catalogue ownership). Touches no WildBerries API."
    )
    parser.add_argument(
        "--email",
        default=DEFAULT_EMAIL,
        help=f"Account email for the browser tier (default: {DEFAULT_EMAIL}).",
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_PASSWORD,
        help="Account password. Reset on every run so the login journey is deterministic.",
    )
    return parser.parse_args()


async def main() -> None:
    """Seed the fixtures and print a one-line report."""
    args = _parse_args()
    try:
        report = await seed(email=args.email, password=args.password)
    finally:
        await engine.dispose()

    verb = "created" if report.account_created else "updated"
    print(
        f"E2E fixtures ready: account {report.email} {verb}; "
        f"workspaces={report.workspaces}; "
        f"cards claimed={report.cards_claimed}, visible={report.cards_visible}"
    )
    if not report.cards_visible:
        print(
            "  WARNING: the primary workspace can see no SKUs. Load the catalogue "
            "first (backend/scripts/load_seed.sh), then re-run this script."
        )


if __name__ == "__main__":
    asyncio.run(main())
