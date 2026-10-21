"""The settlement-week fixture the end-to-end tier's finreports journeys need.

Split out of `seed_e2e_fixtures` when that script passed the 500-line ceiling.
It is a responsibility of its own: everything else there provisions the ACCOUNT
and its tenancy, while this builds one week of settlement data complete enough
for the P&L to show non-zero figures — which is the part with the domain
knowledge in it, and the part that made an empty database look like a broken
page.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.constants import LOGISTICS_OPER, PENALTY_OPER
from src.modules.finreports.models import FinancialReport, LogisticsTransaction
from src.modules.monitoring.models import ProductCard

__all__ = ["ensure_finreports_week"]

#: Synthetic WB identifiers for the finreports week. Deliberately far above any
#: id WB has ever issued, so a fixture row can never collide with — or be
#: mistaken for — a harvested one on a stack where both exist.
_FIXTURE_REPORT_ID = 990_000_001
_FIXTURE_RRD_LOGISTICS = 990_000_101
_FIXTURE_RRD_PENALTY = 990_000_102
_FIXTURE_GI_ID = 990_000_301

#: The fixture SKU when the catalogue is empty (normally a real seeded nm_id is
#: adopted instead, so the report links to a card the UI can also open).
_FALLBACK_NM_ID = 990_000_501

#: The week's two charges: one «Логистика» (delivery) row and one «Штраф»
#: (penalty) row, so the statement's logistics and penalty lines both show.
_LOGISTICS_BILLED_KGS = Decimal("278.00")
_PENALTY_KGS = Decimal("400.00")
_PENALTY_REASON = "E2E fixture"
_FIXTURE_WAREHOUSE = "Коледино"


async def ensure_finreports_week(session: AsyncSession, workspace_id: uuid.UUID) -> bool:
    """Create one internally consistent week of settlement data.

    Two tables have to agree before the P&L shows a single number:

    * ``financial_report`` — which weeks the period selector may offer at all.
    * ``logistics_transaction`` — what WB actually billed. Two rows: the
      «Логистика» charge and a «Штраф» (penalty); the statement keys off those
      exact WB operation labels.

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
    # once (report 990000001 landed in a developer's workspace via a stray local `make
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

    # Prefer a real catalogue SKU: the settlement rows then name a card the SKU
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
            bonus_type_name=_PENALTY_REASON,
            penalty=_PENALTY_KGS,
            **common,
        )
    )
    return True
