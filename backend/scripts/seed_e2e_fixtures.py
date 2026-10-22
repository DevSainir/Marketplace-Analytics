"""Provision the offline fixtures the end-to-end tier needs, in one run.

The browser tier drives a REAL stack, so it needs three things to exist before
Playwright opens a page — and none of them are supplied by the schema or the
migrations:

1. **An account it can log in as.** The registration form leads to an account
   that belongs to no company and can reach nothing, so a fresh database has
   nobody the tier could use.
2. **At least two workspaces.** Every data request carries ``X-Workspace-Id``,
   and the header is rejected unless the workspace row exists. Two, not one, so
   the "switching workspace re-scopes every request" journey has somewhere to
   switch to instead of skipping itself.
3. **A shop in the first one.** The catalogue, its funnel, advertising and
   settlement weeks — the same fabricated shop `make demo` shows
   (:mod:`scripts.seed_demo`), written into the primary workspace. Without it
   the SKU search finds nothing and the P&L has no weeks to offer, and both
   journeys fail on pages that are working exactly as designed.

Like the demo, this is **fully offline**: it touches no WildBerries surface and
needs no API token. That is what makes it usable from CI.

Every step is idempotent — an existing account keeps its id (its password is
reset to the expected one), existing workspaces are reused, and the shop is
written only into a primary workspace that has no catalogue yet. Re-running is
the intended way to repair a half-seeded stack.

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
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.seed_demo.shop import populate_workspace
from scripts.seed_demo.tenancy import real_data
from src.core.config import settings
from src.core.database import AsyncSessionLocal, engine
from src.core.security import hash_password
from src.core.timeutils import moscow_today
from src.modules.monitoring.models import ProductCard
from src.modules.organizations.models import (
    DEFAULT_SUBSCRIPTION_DAYS,
    MemberRole,
    Membership,
    Organization,
    Subscription,
)
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
#: The tenant the seeded account owns. One is enough: the tier exercises what a
#: customer sees inside their own company, and a second organisation would only
#: add a boundary no browser journey crosses.
E2E_ORGANIZATION_NAME: str = "E2E Company"

DEFAULT_WORKSPACE_NAMES: tuple[str, str] = ("E2E Primary", "E2E Secondary")


@dataclass(frozen=True)
class SeedReport:
    """What one run changed, for the log line CI operators read.

    Attributes:
        email: The account the tier will log in as.
        account_created: ``True`` when the user row did not exist before.
        workspaces: Names of the workspaces present after the run, oldest first.
        shop_written: ``True`` when the shop was written by this run.
        cards_visible: Cards the primary workspace can see after the run.
    """

    email: str
    account_created: bool
    workspaces: list[str]
    shop_written: bool
    cards_visible: int


async def _ensure_account(session: AsyncSession, *, email: str, password: str) -> tuple[User, bool]:
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
        The account, and ``True`` when it was inserted rather than updated.
    """
    digest = await asyncio.to_thread(hash_password, password)
    existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        existing.hashed_password = digest
        existing.is_active = True
        # The tier exercises the workspace admin panel, which is dev-gated.
        existing.role = ROLE_DEV
        # Reset forward like the password, and for the same reason: a stack
        # reseeded from an older dump carries accounts predating the login
        # confirmation gate, and `/login` refuses an unproven address.
        existing.email_confirmed_at = datetime.now(UTC)
        return existing, False
    account = User(
        email=email,
        hashed_password=digest,
        is_active=True,
        role=ROLE_DEV,
        # A seeded account exists to be logged into, and `/login` now refuses an
        # unconfirmed address. There is no mailbox in this tier to prove one
        # from, so the seed asserts it the same way it asserts the password.
        email_confirmed_at=datetime.now(UTC),
    )
    session.add(account)
    await session.flush()
    return account, True


async def _ensure_organization(session: AsyncSession, *, owner: User) -> Organization:
    """Guarantee a tenant for the seeded account to own, with a live term.

    Workspaces became NOT NULL on `organization_id`, so there is no longer such
    a thing as a workspace belonging to nobody — the seed has to create the
    company before it can create anything the browser tier can see. The account
    is made its OWNER rather than a manager, because the tier drives the
    workspace admin panel, and creating a workspace is an owner's right.

    The subscription is reset forward on every run for the same reason the
    password is: a stack reseeded from a dump of unknown provenance may carry an
    expired term, and an expired term is read-only — which would fail the
    write journeys with a message indistinguishable from a real regression.

    Args:
        session: Open async session (the caller owns the transaction).
        owner: The seeded account.

    Returns:
        The organisation, flushed so its id can be referenced.
    """
    organization = (
        (await session.execute(select(Organization).order_by(Organization.created_at)))
        .scalars()
        .first()
    )
    if organization is None:
        organization = Organization(name=E2E_ORGANIZATION_NAME, is_primary=True)
        session.add(organization)
        await session.flush()

    membership = (
        await session.execute(select(Membership).where(Membership.user_id == owner.id))
    ).scalar_one_or_none()
    if membership is None:
        session.add(
            Membership(
                organization_id=organization.id,
                user_id=owner.id,
                role=MemberRole.OWNER.value,
            )
        )
    else:
        membership.organization_id = organization.id
        membership.role = MemberRole.OWNER.value

    now = datetime.now(UTC)
    subscription = (
        (
            await session.execute(
                select(Subscription).where(Subscription.organization_id == organization.id)
            )
        )
        .scalars()
        .first()
    )
    if subscription is None:
        session.add(
            Subscription(
                organization_id=organization.id,
                started_at=now,
                expires_at=now + timedelta(days=DEFAULT_SUBSCRIPTION_DAYS),
                grace_days=settings.subscription_grace_days,
            )
        )
    else:
        subscription.expires_at = now + timedelta(days=DEFAULT_SUBSCRIPTION_DAYS)

    await session.flush()
    return organization


async def _ensure_workspaces(
    session: AsyncSession, *, organization_id: uuid.UUID
) -> list[Workspace]:
    """Guarantee at least two workspaces exist, returning them oldest first.

    Args:
        session: Open async session (the caller owns the transaction).
        organization_id: The tenant every seeded workspace belongs to.

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
        workspace = Workspace(name=name, is_primary=not existing, organization_id=organization_id)
        session.add(workspace)
        existing.append(workspace)
    await session.flush()
    return existing


async def _count_visible_cards(session: AsyncSession, workspace_id: uuid.UUID) -> int:
    """Count the cards a workspace can see (what the SKU search will find)."""
    stmt = (
        select(func.count())
        .select_from(ProductCard)
        .where(ProductCard.workspace_id == workspace_id)
    )
    return int(await session.scalar(stmt) or 0)


async def seed(*, email: str, password: str) -> SeedReport:
    """Provision the account, the workspaces, and the shop in the first of them.

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
        account, created = await _ensure_account(
            session, email=email.strip().lower(), password=password
        )
        organization = await _ensure_organization(session, owner=account)
        workspaces = await _ensure_workspaces(session, organization_id=organization.id)
        primary = workspaces[0]
        # The shop's WB ids are fixed, so it is written once: a primary
        # workspace that already sees a catalogue keeps it. And never beside
        # real data — a stray local run once put a fixture week into a
        # developer's workspace, where it skewed every window covering it.
        found = await real_data(session)
        shop_written = not found and not await _count_visible_cards(session, primary.id)
        if shop_written:
            await populate_workspace(session, primary.id, moscow_today())
        elif found:
            listed = ", ".join(f"{count} {kind}" for kind, count in found.items())
            print(f"  SKIPPED the shop: this database already holds {listed}.")
        visible = await _count_visible_cards(session, primary.id)
        await session.commit()

    return SeedReport(
        email=email,
        account_created=created,
        workspaces=[workspace.name for workspace in workspaces],
        shop_written=shop_written,
        cards_visible=visible,
    )


def _parse_args() -> argparse.Namespace:
    """Parse the command-line options."""
    parser = argparse.ArgumentParser(
        description="Seed the offline fixtures the end-to-end tier needs (account, "
        "workspaces, the demo shop). Touches no WildBerries API."
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
        f"shop={'written' if report.shop_written else 'already present'}, "
        f"cards visible={report.cards_visible}"
    )


if __name__ == "__main__":
    asyncio.run(main())
