"""WB's own payout total for a report, against ours.

``sales-reports/list`` carries ``forPaySum`` per report, so a booked report can
be checked against something that is not our own arithmetic —
``docs/finreports/PNL.md`` warns that most ways to get a settlement figure wrong
produce a plausible statement rather than an error.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import get_logger
from src.core.observability.metrics import SETTLEMENT_PAYOUT_DIVERGENCE
from src.integrations.wildberries.schemas import WBFinanceReportHeader
from src.modules.finreports.constants import REFUND_DOC_TYPE
from src.modules.finreports.models import LogisticsTransaction

logger = get_logger(__name__)

#: The payout column, named once so the signed sum below stays readable.
_FOR_PAY = LogisticsTransaction.ppvz_for_pay


async def reconcile_against_wb(
    session: AsyncSession, *, header: WBFinanceReportHeader, workspace_id: uuid.UUID, name: str
) -> Decimal | None:
    """Compare our payout for one report against WB's own figure.

    The oracle the P&L has never had. ``docs/finreports/PNL.md`` warns that
    most ways to get a settlement figure wrong produce a plausible statement
    rather than an error; ``sales-reports/list`` carries WB's own
    ``forPaySum`` for the same report, so for the first time the statement can
    be checked against something.

    **What WB totals is not a plain sum.** Worked out against a real report on
    2026-09-22: ``forPaySum`` is «Продажа» minus «Возврат» minus «Коррекция
    продаж» plus the standalone compensations — e.g. 1 000 000.00 - 120 000.00 -
    50.00 + 8 000.00 = 887 950.00, to the kopeck. The sign is never in the
    value: WB serves refunds POSITIVE, which is the mistake that doubles
    revenue if a reader sums the column.

    That reconstruction found one live disagreement on its first use, and the
    rule that settled it is not the operation at all: WB negates every row whose
    document type is «Возврат», see
    :data:`~src.modules.finreports.constants.REFUND_DOC_TYPE`.

    Args:
        session: An open session. Nothing here writes.
        header: The report header as `sales-reports/list` served it.
        workspace_id: Whose rows to total.
        name: The seller's name, for the log line only.

    Returns:
        WB's figure minus ours, or ``None`` when we hold no rows for the
        report yet. Zero is agreement.
    """
    ours = (
        await session.execute(
            select(
                func.sum(
                    case(
                        (LogisticsTransaction.doc_type_name == REFUND_DOC_TYPE, -_FOR_PAY),
                        else_=_FOR_PAY,
                    )
                )
            ).where(
                LogisticsTransaction.workspace_id == workspace_id,
                LogisticsTransaction.report_id == header.report_id,
            )
        )
    ).scalar_one_or_none()
    if ours is None:
        return None
    difference: Decimal = header.for_pay_sum - ours
    SETTLEMENT_PAYOUT_DIVERGENCE.observe(abs(float(difference)))
    if difference:
        logger.warning(
            "finreports: report %d for %s totals %s here against WB's %s — %s apart.",
            header.report_id,
            name,
            ours,
            header.for_pay_sum,
            difference,
        )
    return difference


__all__ = ["reconcile_against_wb"]
