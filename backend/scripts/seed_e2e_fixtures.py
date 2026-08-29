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
   weeks to offer, renders «0 недель» with the export button disabled, and its
   journey fails on a page that is working exactly as designed. The facts are
   spread over six tables that only mean something together — see
   :func:`_ensure_finreports_week`.

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
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import AsyncSessionLocal, engine
from src.core.security import hash_password
from src.modules.finreports.constants import (
    LOGISTICS_OPER,
    PENALTY_OPER,
)
from src.modules.finreports.models import (
    FinancialReport,
    LogisticsTransaction,
)
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

#: Synthetic WB identifiers for the finreports week. Deliberately far above any
#: id WB has ever issued, so a fixture row can never collide with — or be
#: mistaken for — a harvested one on a stack where both exist.
_FIXTURE_REPORT_ID = 990_000_001
_FIXTURE_RRD_LOGISTICS = 990_000_101
_FIXTURE_RRD_PENALTY = 990_000_102
_FIXTURE_DIM_ID = 990_000_201
_FIXTURE_GI_ID = 990_000_301
_FIXTURE_CHRT_ID = 990_000_401

#: The fixture SKU when the catalogue is empty (normally a real seeded nm_id is
#: adopted instead, so the report links to a card the UI can also open).
_FALLBACK_NM_ID = 990_000_501

#: load-bearing: WB bills 20 litres for a box the seller measured at 10, so the
_DECLARED_VOLUME_L = Decimal("10.000")
_BILLED_VOLUME_L = Decimal("20.000")
_LOGISTICS_BILLED_KGS = Decimal("278.00")
_BOX_DELIVERY_BASE = Decimal("46.00")
_BOX_DELIVERY_LITER = Decimal("14.00")
_FIXTURE_WAREHOUSE = "Коледино"


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
    finreports_week_created: bool


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
        return existing, False
    account = User(email=email, hashed_password=digest, is_active=True, role=ROLE_DEV)
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


async def _ensure_finreports_week(session: AsyncSession, workspace_id: uuid.UUID) -> bool:

    Six tables have to agree before the report shows a single number, and each
    one answers a different question:

    * ``financial_report`` — which weeks the period selector may offer at all.
    * ``logistics_transaction`` — what WB actually billed. Two rows: the
      «Логистика» charge, and the «Штраф» whose ``bonus_type_name`` is the
      ``source="seller"`` so it outranks any card-derived row.
      Without it the service falls back to defaults and flags the total as
      resting on an assumed tariff.
      empty-database failure look like a broken page.

    The window is anchored to last week rather than a fixed calendar date, so
    the fixture stays inside any default settlement window the API applies.

    Args:
        session: Open async session (the caller owns the transaction).
        workspace_id: The tenant the week belongs to.

    Returns:
        ``True`` when the week was created, ``False`` when it already existed.
    """
    existing = await session.get(FinancialReport, _FIXTURE_REPORT_ID)
    if existing is not None:
        return False

    # Safety guard — the reason this function cannot pollute real data again.
    # The e2e fixture DB holds nothing but what this script seeds, so it has zero
    # non-fixture settlement rows and the guard is a no-op. A developer's dev DB
    # (or prod) holds hundreds of thousands of real rows; injecting a fake demo
    # "week" onto a real SKU there silently skews the P&L. That accident happened
    # once (report 990000001 landed in «Демо» via a stray local `make
    # seed-e2e`), so this refuses outright rather than trusting the .env target.
    real_rows = await session.scalar(
        select(func.count())
        .select_from(LogisticsTransaction)
        .where(LogisticsTransaction.report_id != _FIXTURE_REPORT_ID)
    )
    if real_rows:
        print(
            f"  SKIPPED finreports fixture: database already has {real_rows} real "
            "settlement rows. This seeder is for a fresh e2e database only — it "
            "refuses to inject the demo week into populated (dev/prod) data."
        )
        return False

    today = date.today()
    date_to = today - timedelta(days=7)
    date_from = date_to - timedelta(days=6)

    # search and the matrix can also open, so a failure is traceable across
    # both journeys instead of pointing at an id that exists nowhere else.
    nm_id = await session.scalar(
        select(func.min(ProductCard.nm_id)).where(ProductCard.workspace_id == workspace_id)
    )
    nm_id = int(nm_id) if nm_id is not None else _FALLBACK_NM_ID
    vendor_code = await session.scalar(
        select(ProductCard.vendor_code).where(ProductCard.nm_id == nm_id)
    )
    sa_name = str(vendor_code or "E2E-FIXTURE")

    session.add(
        FinancialReport(
            report_id=_FIXTURE_REPORT_ID,
            workspace_id=workspace_id,
            date_from=date_from,
            date_to=date_to,
            currency="KGS",
            create_dt=date_to,
        )
    )
    common = {
        "report_id": _FIXTURE_REPORT_ID,
        "workspace_id": workspace_id,
        "nm_id": nm_id,
        "sa_name": sa_name,
        "rr_dt": date_to,
        "currency_name": "KGS",
        "office_name": _FIXTURE_WAREHOUSE,
        "gi_id": _FIXTURE_GI_ID,
    }
    session.add(
        LogisticsTransaction(
            rrd_id=_FIXTURE_RRD_LOGISTICS,
            supplier_oper_name=LOGISTICS_OPER,
            quantity=1,
            delivery_amount=1,
            delivery_rub=_LOGISTICS_BILLED_KGS,
            **common,
        )
    )
    session.add(
        LogisticsTransaction(
            rrd_id=_FIXTURE_RRD_PENALTY,
            supplier_oper_name=PENALTY_OPER,
            **common,
        )
    )
    session.add(
            nm_id=nm_id,
            snapshot_date=date_from,
            source="seller",
            vendor_code=sa_name,
            volume_l=_DECLARED_VOLUME_L,
            workspace_id=workspace_id,
        )
    )
    session.add(
            observed_date=date_to,
            warehouse_name=_FIXTURE_WAREHOUSE,
            gi_id=_FIXTURE_GI_ID,
            chrt_id=_FIXTURE_CHRT_ID,
            nm_id=nm_id,
            volume_l=_BILLED_VOLUME_L,
        )
    )
    session.add(
            snapshot_date=date_from,
            warehouse_name=_FIXTURE_WAREHOUSE,
            box_delivery_base=_BOX_DELIVERY_BASE,
            box_delivery_liter=_BOX_DELIVERY_LITER,
        )
    )
    session.add(
            nm_id=nm_id,
            dim_id=_FIXTURE_DIM_ID,
            dt_bonus=date_to,
            subject_name="E2E fixture",
            volume_sup=_DECLARED_VOLUME_L,
            volume=_BILLED_VOLUME_L,
            is_valid=True,
            workspace_id=workspace_id,
        )
    )
    return True


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
        account, created = await _ensure_account(
            session, email=email.strip().lower(), password=password
        )
        organization = await _ensure_organization(session, owner=account)
        workspaces = await _ensure_workspaces(session, organization_id=organization.id)
        primary = workspaces[0]
        claimed = await _claim_unowned_cards(session, primary.id)
        visible = await _count_visible_cards(session, primary.id)
        # After the claim, so the fixture week can adopt a card the workspace
        # can actually see.
        week_created = await _ensure_finreports_week(session, primary.id)
        await session.commit()

    return SeedReport(
        email=email,
        account_created=created,
        workspaces=[workspace.name for workspace in workspaces],
        cards_claimed=claimed,
        cards_visible=visible,
        finreports_week_created=week_created,
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
        f"cards claimed={report.cards_claimed}, visible={report.cards_visible}; "
        f"finreports week={'created' if report.finreports_week_created else 'already present'}"
    )
    if not report.cards_visible:
        print(
            "  WARNING: the primary workspace can see no SKUs. Load the catalogue "
            "first (backend/scripts/load_seed.sh), then re-run this script."
        )


if __name__ == "__main__":
    asyncio.run(main())
