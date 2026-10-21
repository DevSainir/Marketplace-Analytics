"""Shared fixture for the P&L integration tests.

One miniature WB week, seeded once and used by both
``test_pnl_reconciles.py`` (does the arithmetic close?) and
``test_pnl_caveats.py`` (does the statement admit what it cannot verify?). It
lives here rather than in either file because the two split out of one module
that outgrew the 500-line ceiling, and duplicating a fifteen-row financial
fixture is how the two halves start disagreeing about what the week contained.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.models import FinancialReport, LogisticsTransaction, ProductCostPrice
from src.modules.finreports.repos import (
    CostPriceRepository,
    FinancialReportRepository,
    PnlGrouping,
    PnlRepository,
)
from src.modules.finreports.services import PnlService

pytestmark = pytest.mark.integration

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000beef")
OTHER_WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-0000000000aa")

THIS_WEEK = 969371534
LAST_WEEK = 785000000
WINDOW_FROM = date(2026, 7, 13)
WINDOW_TO = date(2026, 7, 19)

SKU_A = 953770957
SKU_B = 995716075
COST_A = Decimal("662")
COST_B = Decimal("700")

_FILLER_OPER = "Возмещение издержек по перевозке/по складским операциям с товаром"


def _row(rrd_id: int, oper: str, *, report: int = THIS_WEEK, rr_dt: date = WINDOW_FROM, **fields):
    """One settlement row with every unspecified money column at zero."""
    base = {
        "rrd_id": rrd_id,
        "report_id": report,
        "workspace_id": WORKSPACE,
        "nm_id": 0,
        "supplier_oper_name": oper,
        "rr_dt": rr_dt,
        "currency_name": "KGS",
    }
    return LogisticsTransaction(**{**base, **fields})


def _sale(rrd_id: int, nm_id: int, *, rr_dt: date, report: int, paid: str, payout: str, acq: str):
    """A «Продажа» row obeying the payout identity."""
    return _row(
        rrd_id,
        "Продажа",
        report=report,
        rr_dt=rr_dt,
        nm_id=nm_id,
        sa_name=f"sku-{nm_id}",
        quantity=1,
        retail_amount=Decimal(paid),
        retail_price_withdisc_rub=Decimal(paid) * 2,
        ppvz_for_pay=Decimal(payout),
        acquiring_fee=Decimal(acq),
        ppvz_vw=Decimal(paid) - Decimal(payout) - Decimal(acq),
        payment_processing="Компенсация платёжных услуг",
        agency_vat=Decimal("100"),
    )


@pytest.fixture
async def seeded(db_session: AsyncSession) -> None:
    """One miniature week, plus a neighbouring week and a foreign workspace."""
    db_session.add_all(
        [
            FinancialReport(
                report_id=THIS_WEEK,
                workspace_id=WORKSPACE,
                date_from=WINDOW_FROM,
                date_to=WINDOW_TO,
                currency="KGS",
            ),
            # Two sales this week.
            _sale(
                1, SKU_A, rr_dt=WINDOW_FROM, report=THIS_WEEK, paid="1000", payout="900", acq="30"
            ),
            _sale(
                2, SKU_B, rr_dt=WINDOW_TO, report=THIS_WEEK, paid="2000", payout="1800", acq="60"
            ),
            # A refund of a sale settled in an EARLIER week — served positive.
            _row(
                3,
                "Возврат",
                nm_id=SKU_A,
                sa_name=f"sku-{SKU_A}",
                rr_dt=WINDOW_TO,
                quantity=1,
                retail_amount=Decimal("500"),
                retail_price_withdisc_rub=Decimal("1000"),
                ppvz_for_pay=Decimal("450"),
                acquiring_fee=Decimal("15"),
                ppvz_vw=Decimal("35"),
                agency_vat=Decimal("50"),
            ),
            # Both logistics legs — exactly one counter set on each.
            _row(4, "Логистика", nm_id=SKU_A, delivery_amount=1, delivery_rub=Decimal("120")),
            _row(5, "Логистика", nm_id=SKU_A, return_amount=1, delivery_rub=Decimal("80")),
            # Account-level charges (nm_id 0).
            _row(6, "Хранение", storage_fee=Decimal("40")),
            _row(
                7,
                "Штраф",
                penalty=Decimal("25"),
                bonus_type_name="Штраф за нарушение правил маркировки",
            ),
            _row(
                8,
                "Удержание",
                deduction=Decimal("300"),
                bonus_type_name="Оказание услуг «WB Продвижение», документ №1",
            ),
            # A compensation: ppvz_for_pay and nothing else.
            _row(9, "Компенсация ущерба", nm_id=SKU_B, quantity=1, ppvz_for_pay=Decimal("70")),
            # The filler operation, shaped like WB's rows: quantity 2, no
            # product identity, and its charge ALSO republished across the two
            # commission columns as its own VAT split. That last part is what
            # makes this row load-bearing — over a full history those columns
            # carry sizeable sums here, and summing them alongside the sales is
            # what put «в т.ч. НДС комиссии» far out and sign-flipped it on
            # several weeks.
            _row(
                10,
                _FILLER_OPER,
                quantity=2,
                rebill_logistic_cost=Decimal("5"),
                ppvz_vw=Decimal("-4.46"),
                ppvz_vw_nds=Decimal("-0.54"),
            ),
            # A sale in the neighbouring week — must not enter this window.
            _sale(
                11,
                SKU_A,
                rr_dt=date(2026, 7, 6),
                report=LAST_WEEK,
                paid="9999",
                payout="9000",
                acq="1",
            ),
            # Another tenant's sale in the SAME week — must never be visible.
            LogisticsTransaction(
                rrd_id=12,
                report_id=THIS_WEEK,
                workspace_id=OTHER_WORKSPACE,
                nm_id=SKU_A,
                supplier_oper_name="Продажа",
                rr_dt=WINDOW_FROM,
                currency_name="KGS",
                quantity=1,
                retail_amount=Decimal("777777"),
                ppvz_for_pay=Decimal("777777"),
            ),
            ProductCostPrice(
                workspace_id=WORKSPACE, nm_id=SKU_A, cost=COST_A, currency="KGS", source="seed"
            ),
            ProductCostPrice(
                workspace_id=WORKSPACE, nm_id=SKU_B, cost=COST_B, currency="KGS", source="seed"
            ),
        ]
    )
    await db_session.flush()


def _service(session: AsyncSession) -> PnlService:
    """Wire the read service on the test session."""
    return PnlService(
        pnl_repo=PnlRepository(session),
        cost_repo=CostPriceRepository(session),
        report_repo=FinancialReportRepository(session),
    )


async def _statement(session: AsyncSession, grouping: PnlGrouping = PnlGrouping.WEEK):
    """Build the statement for the seeded window."""
    return await _service(session).get_statement(
        workspace_id=WORKSPACE, date_from=WINDOW_FROM, date_to=WINDOW_TO, grouping=grouping
    )
