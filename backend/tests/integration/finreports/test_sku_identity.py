"""What names a SKU on the balance grid — the newest settlement row, per tenant.

The balance table lists every SKU still holding stock, and WB stamps the
article, subject and brand onto the settlement rows rather than publishing them
as a catalogue. Which row is read is a visible product decision: a card renamed
in July must show its July name, not whichever of its names happens to sort
highest. Integration tier because the answer is the query's — an aggregate over
the history and a per-SKU lookup return different strings from the same rows.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.models import LogisticsTransaction
from src.modules.finreports.repos import PnlRepository
from tests.support import wb_labels as wb

pytestmark = pytest.mark.integration

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000d1d1")
OTHER_WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000d2d2")

RENAMED = 953770957
NEVER_SETTLED = 999000111


def _settlement(
    rrd_id: int,
    nm_id: int,
    *,
    rr_dt: date,
    sa_name: str,
    subject: str = "Trousers",
    brand: str = "NoName",
    workspace: uuid.UUID = WORKSPACE,
) -> LogisticsTransaction:
    """One sale row carrying nothing but the SKU's identity of that day."""
    return LogisticsTransaction(
        rrd_id=rrd_id,
        report_id=969371534,
        workspace_id=workspace,
        nm_id=nm_id,
        supplier_oper_name=wb.SALE,
        rr_dt=rr_dt,
        currency_name="KGS",
        sa_name=sa_name,
        subject_name=subject,
        brand_name=brand,
        quantity=1,
        retail_amount=Decimal("1000"),
        ppvz_for_pay=Decimal("900"),
    )


async def test_a_renamed_sku_carries_its_newest_name(db_session: AsyncSession) -> None:
    """The identity comes off the LATEST settlement row, not the greatest string.

    «a-old» sorts after «M-NEW» — an aggregate over the history would hand the
    balance grid the retired article and the retired brand, which is what the
    seller would read as the table naming the wrong product.
    """
    db_session.add_all(
        [
            _settlement(
                1, RENAMED, rr_dt=date(2026, 7, 6), sa_name="a-old", brand="Old", subject="Shorts"
            ),
            _settlement(
                2, RENAMED, rr_dt=date(2026, 8, 3), sa_name="M-NEW", brand="New", subject="Trousers"
            ),
        ]
    )
    await db_session.flush()

    identity = await PnlRepository(db_session).sku_identity(
        workspace_id=WORKSPACE, nm_ids=[RENAMED]
    )

    assert identity == {RENAMED: ("M-NEW", "Trousers", "New")}


async def test_another_tenants_rows_never_name_a_sku(db_session: AsyncSession) -> None:
    """A foreign workspace's newer row for the same nm_id is not an identity.

    WB nm_ids are global, so two sellers of the same catalogue item settle rows
    against the same number; without the tenancy predicate the grid would name a
    SKU with a stranger's article.
    """
    db_session.add_all(
        [
            _settlement(3, RENAMED, rr_dt=date(2026, 7, 6), sa_name="ours"),
            _settlement(
                4,
                RENAMED,
                rr_dt=date(2026, 9, 1),
                sa_name="theirs",
                workspace=OTHER_WORKSPACE,
            ),
        ]
    )
    await db_session.flush()

    identity = await PnlRepository(db_session).sku_identity(
        workspace_id=WORKSPACE, nm_ids=[RENAMED]
    )

    assert identity[RENAMED][0] == "ours"


async def test_a_sku_that_never_settled_is_absent(db_session: AsyncSession) -> None:
    """A SKU with stock but no settlement history gets no entry at all.

    Absence is the signal the caller acts on: it falls back to the catalogue
    vendor code, and an empty-string triple would defeat that and render a bare
    nm_id in the "Vendor code" column.
    """
    db_session.add(_settlement(5, RENAMED, rr_dt=date(2026, 7, 6), sa_name="present"))
    await db_session.flush()

    identity = await PnlRepository(db_session).sku_identity(
        workspace_id=WORKSPACE, nm_ids=[RENAMED, NEVER_SETTLED]
    )

    assert NEVER_SETTLED not in identity
