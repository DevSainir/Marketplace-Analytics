"""Who funded the advertising — the bonus side of the P&L's "Advertising".

Split out of :mod:`.exports` (it crossed the file ceiling) because it answers a
different question from the loaders there. Those say what a SKU earned and what
its ads cost; these say how much of that cost WB paid instead of the seller.

The distinction matters because the two feeds disagree by construction. WB's
``fullstats`` reports every impression a campaign served whoever funded it, and
the weekly settlement report never sees a bonus charge at all — a cashback
write-off carries no invoice document, so no "WB Promotion" services
deduction row is ever raised for it. On one account checked over a fortnight in September
2026, WB had funded a large share of the write-offs, and every som of it was
being reported as the seller's own spend.

Same rules as :mod:`.exports`: module-level functions, the caller owns the
session, and nothing here is imported except through ``contract.py``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from src.modules.monitoring.models import (
    BONUS_PAYMENT_TYPES,
    CASH_PAYMENT_TYPES,
    AdvertisingStatDaily,
    AdvertisingWriteOffDaily,
)
from src.modules.monitoring.repos.base import workspace_sku_select

#: Neutral element for the money sums below.
_ZERO = Decimal(0)


async def load_ad_bonus_by_nm(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> dict[int, Decimal]:
    """Return the WB-funded share of each SKU's advertising, as a POSITIVE magnitude.

    WB pays part of a seller's advertising out of a bonus pool (cashback, up to
    50 % of a charge). Those impressions are in ``fullstats`` like any other, and
    they never reach the settlement report at all — a bonus write-off carries no
    invoice document — so without this the seller's own DRR, ROI and profit count
    WB's money as theirs.

    **The allocation is a model, and it is confined to this function.** WB's
    ledger has no ``nm_id``: a write-off belongs to a campaign. So each campaign's
    bonus for the window is split across that campaign's SKUs in proportion to
    the spend ``fullstats`` booked on them **over the same window**. Four rules
    make that safe enough to put on a report:

    * **The window, not the day.** Write-offs are batched (one large row at 22:45
      against a day of impressions), so a day-grain split would put a
      campaign's whole bonus on whichever SKUs happened to run that evening. Over
      a window the two feeds agree to ~0.1 % per campaign — measured 2026-09.
    * **Never across campaigns.** A campaign's bonus only ever reaches the SKUs
      that campaign advertised.
    * **Clamped at the campaign's own spend.** A write-off dated just inside the
      window whose impressions fell just outside it could otherwise make the
      bonus exceed the spend and print a negative advertising cost.
    * **Matched to the spend, not to the settlement.** A campaign's bonus and its
      spend are in the campaign's own unit — RUB for campaigns created before WB
      moved the ad account to KGS on 2026-08-20, KGS after — and `upd` agrees
      with `fullstats` at 90-100 % per campaign on both sides. (This line once
      called 20.08 a relabel; it was a real move.) Filtering the ledger by the
      SETTLEMENT currency was
      this function's first shape and it was wrong: it dropped most of the
      bonuses for July-August windows because WB labelled the ad account
      differently from the payout. The currency is still kept in storage — it is
      what WB said — and a window carrying more than one is reported as a caveat
      rather than silently summed.

    A campaign that spent nothing in the window contributes nothing: its bonus has
    no SKU to land on, and inventing one is worse than the omission.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to SKUs owned by this workspace.
        date_from: Inclusive stat-date start.
        date_to: Inclusive stat-date end.

    Returns:
        ``{nm_id: bonus}`` as a positive amount to be SUBTRACTED from that SKU's
        advertising; SKUs with no bonus-funded spend are absent.
    """
    # Per campaign: how much bonus the window carries, and how much fullstats
    # spend there is to spread it over. Both are window sums by design.
    bonus_stmt = (
        select(
            AdvertisingWriteOffDaily.campaign_id,
            func.sum(AdvertisingWriteOffDaily.amount),
        )
        .where(
            AdvertisingWriteOffDaily.stat_date >= date_from,
            AdvertisingWriteOffDaily.stat_date <= date_to,
            AdvertisingWriteOffDaily.payment_type.in_(sorted(BONUS_PAYMENT_TYPES)),
        )
        .group_by(AdvertisingWriteOffDaily.campaign_id)
    )
    bonus_by_campaign = {
        int(cid): Decimal(total)
        for cid, total in (await session.execute(bonus_stmt)).all()
        if total
    }
    if not bonus_by_campaign:
        return {}

    # The denominator is the campaign's WHOLE spend, not just its spend on this
    # workspace's SKUs: a share of the bonus that belongs to a card we do not own
    # must be dropped, never redistributed onto the cards we do.
    spend_stmt = (
        select(
            AdvertisingStatDaily.campaign_id,
            AdvertisingStatDaily.nm_id,
            func.sum(AdvertisingStatDaily.spend),
        )
        .where(
            AdvertisingStatDaily.campaign_id.in_(sorted(bonus_by_campaign)),
            AdvertisingStatDaily.stat_date >= date_from,
            AdvertisingStatDaily.stat_date <= date_to,
        )
        .group_by(AdvertisingStatDaily.campaign_id, AdvertisingStatDaily.nm_id)
    )
    spend_rows = [
        (int(cid), int(nm), Decimal(spend))
        for cid, nm, spend in (await session.execute(spend_stmt)).all()
        if spend and Decimal(spend) > 0
    ]
    if not spend_rows:
        return {}

    owned = {
        int(row[0])
        for row in (
            await session.execute(
                select(AdvertisingStatDaily.nm_id)
                .where(AdvertisingStatDaily.nm_id.in_(workspace_sku_select(workspace_id)))
                .group_by(AdvertisingStatDaily.nm_id)
            )
        ).all()
    }

    campaign_spend: dict[int, Decimal] = {}
    for campaign_id, _nm_id, spend in spend_rows:
        campaign_spend[campaign_id] = campaign_spend.get(campaign_id, _ZERO) + spend

    out: dict[int, Decimal] = {}
    for campaign_id, nm_id, spend in spend_rows:
        if nm_id not in owned or campaign_id not in bonus_by_campaign:
            continue
        total_spend = campaign_spend[campaign_id]
        # Clamped before the split, so every SKU's share shrinks by the same
        # factor and the parts still sum to the (clamped) campaign bonus. The
        # clamp is also what bounds the damage if WB ever DID bill one window in
        # two real currencies: a bonus can never exceed the spend it comes off.
        bonus = min(bonus_by_campaign[campaign_id], total_spend)
        share = (bonus * spend / total_spend).quantize(Decimal("0.01"))
        out[nm_id] = out.get(nm_id, _ZERO) + share
    return {nm: amount for nm, amount in out.items() if amount}


def _workspace_campaigns(workspace_id: uuid.UUID) -> Select[tuple[int]]:
    """Subquery: the campaigns that ever advertised this workspace's SKUs.

    The write-off ledger has no tenant column of its own — a charge names a
    campaign, and a campaign is only tied to a seller through the cards it
    served. This is that join, and it is what keeps one account's ledger out of
    another's report.
    """
    return (
        select(AdvertisingStatDaily.campaign_id)
        .where(AdvertisingStatDaily.nm_id.in_(workspace_sku_select(workspace_id)))
        .group_by(AdvertisingStatDaily.campaign_id)
    )


async def ad_bonus_coverage(
    session: AsyncSession, *, workspace_id: uuid.UUID, date_from: date, date_to: date
) -> tuple[date | None, date | None]:
    """Return the write-off days on record for this workspace inside a window.

    Answers "has the funding ledger been harvested for this period", which is
    what separates "there were no bonuses" from "we have not asked about them yet" — the
    distinction that decides whether the column prints ``0`` or nothing at all.

    Scoped to the workspace's own campaigns even though the ledger is fetched
    per advertising token: the table is shared, so a global answer would tell a
    seller whose ledger was never harvested that it was, on the strength of
    another seller's harvest.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to campaigns that advertised this workspace.
        date_from: Inclusive window start.
        date_to: Inclusive window end.

    Returns:
        ``(first, last)`` covered day inside the window, or ``(None, None)``.
    """
    stmt = select(
        func.min(AdvertisingWriteOffDaily.stat_date),
        func.max(AdvertisingWriteOffDaily.stat_date),
    ).where(
        AdvertisingWriteOffDaily.stat_date >= date_from,
        AdvertisingWriteOffDaily.stat_date <= date_to,
        AdvertisingWriteOffDaily.campaign_id.in_(_workspace_campaigns(workspace_id)),
    )
    first, last = (await session.execute(stmt)).one()
    return first, last


async def ad_bonus_unknown_types(
    session: AsyncSession, *, workspace_id: uuid.UUID, date_from: date, date_to: date
) -> list[str]:
    """Return funding labels in the window that are neither known cash nor bonus.

    The bonus match is an allowlist (see
    :data:`~src.modules.monitoring.models.BONUS_PAYMENT_TYPES`), so a label WB
    renames stops being subtracted rather than being guessed at. That is the safe
    default and a silent one — this is what makes it audible, by putting the
    unrecognised label in the report's caveats.

    Not filtered by currency: an unknown label is a contract change worth
    reporting whatever currency it was booked in.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to campaigns that advertised this workspace.
        date_from: Inclusive window start.
        date_to: Inclusive window end.

    Returns:
        The unrecognised ``paymentType`` labels, alphabetically.
    """
    known = sorted(BONUS_PAYMENT_TYPES | CASH_PAYMENT_TYPES)
    stmt = (
        select(AdvertisingWriteOffDaily.payment_type)
        .where(
            AdvertisingWriteOffDaily.stat_date >= date_from,
            AdvertisingWriteOffDaily.stat_date <= date_to,
            AdvertisingWriteOffDaily.campaign_id.in_(_workspace_campaigns(workspace_id)),
            AdvertisingWriteOffDaily.payment_type.notin_(known),
        )
        .group_by(AdvertisingWriteOffDaily.payment_type)
        .order_by(AdvertisingWriteOffDaily.payment_type)
    )
    return [str(row[0]) for row in (await session.execute(stmt)).all()]
