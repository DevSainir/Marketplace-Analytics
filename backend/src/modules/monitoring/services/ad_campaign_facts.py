"""The кабинет's advertising at CAMPAIGN grain — the raw facts the «Реклама» page composes.

Every other ad loader in this module answers one question at one grain: spend
per SKU, spend per day, bonus per SKU over a window. The advertising page asks
all of them at once and needs them to agree to the сом — the zone table, the
daily chart, the per-article table and the headline cards are four cuts of the
same money. That only holds if they are cut from the same rows, so this loader
hands out the rows themselves, at the finest grain the page needs, and leaves
the arithmetic to the consumer:

* spend per ``(campaign, day, nm_id)`` from ``fullstats`` — summed over WB's
  platforms (``app_type``), which no consumer distinguishes;
* the SEARCH-zone slice per ``(campaign, day)`` from ``normquery`` — the input
  the zone split is computed from (see ``matrix/classification.py``);
* the WB-funded bonus per ``(campaign, charge day)`` from the write-off ledger;
* each campaign's payment model, bid model and placements.

Tenancy. Spend and the search slice carry ``nm_id`` and are scoped through
``workspace_sku_select``. The campaign dimension and the ledger carry no tenant
at all, so both are restricted to the campaigns that spent on this кабинет's
cards in the window — and the ledger's bonus is scaled by the кабинет's share of
each campaign's window spend, so a campaign that also advertised a card we do
not own can never hand its whole bonus to the cards we do (the same rule as
:func:`~src.modules.monitoring.services.ad_bonus.load_ad_bonus_by_nm`).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import (
    BONUS_PAYMENT_TYPES,
    AdvertisingSearchStatDaily,
    AdvertisingStatDaily,
    AdvertisingWriteOffDaily,
    Campaign,
)
from src.modules.monitoring.repos.base import workspace_sku_select

_CENT = Decimal("0.01")


class AdCampaignMeta(NamedTuple):
    """How a campaign is billed and where it shows — ``None`` until WB's settings synced."""

    campaign_id: int
    #: ``cpm`` or ``cpc``.
    payment_type: str | None
    #: ``manual`` (ручная ставка) or ``unified`` (единая ставка).
    bid_type: str | None
    placement_search: bool | None
    placement_recommendations: bool | None


class AdCampaignSpend(NamedTuple):
    """One campaign's ``fullstats`` spend on one of the кабинет's cards on one day."""

    campaign_id: int
    stat_date: date
    nm_id: int
    spend: Decimal


class AdCampaignSearch(NamedTuple):
    """One campaign-day's SEARCH-zone spend on the кабинет's cards (normquery)."""

    campaign_id: int
    stat_date: date
    spend: Decimal


class AdCampaignBonus(NamedTuple):
    """WB-funded spend charged to a campaign on one day, already scaled to this кабинет.

    ``stat_date`` is the CHARGE day: WB writes bonuses off in batches, so it
    aligns with the spend over a run of days rather than day by day.
    """

    campaign_id: int
    stat_date: date
    amount: Decimal


class AdCampaignFacts(NamedTuple):
    """Everything the advertising page composes, for one кабинет and window."""

    campaigns: list[AdCampaignMeta]
    spend: list[AdCampaignSpend]
    search: list[AdCampaignSearch]
    bonus: list[AdCampaignBonus]
    #: The currencies the window's spend was billed in — the same answer as
    #: :func:`~.sku_day_facts.load_ad_currencies`, read off these rows rather
    #: than by a second pass over the window.
    currencies: tuple[str, ...] = ()
    #: Whether WB's funding ledger has ANY row for these campaigns in the
    #: window — what separates «бонусов не было» from «журнал не собран».
    ledger_known: bool = False


async def load_ad_campaign_facts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> AdCampaignFacts:
    """Return the window's campaign-grain advertising facts for one кабинет.

    Money is in the кабинет's currency where the FX sweep has converted it
    (``repos/ad_money.py``); a consumer that must not mix units asks
    :func:`~src.modules.monitoring.services.sku_day_facts.load_ad_currencies`.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to this workspace's cards and their campaigns.
        date_from: Inclusive day start (ad-run day for spend, charge day for bonus).
        date_to: Inclusive day end.
    """
    owned = workspace_sku_select(workspace_id)

    spend_rows = (
        await session.execute(
            select(
                AdvertisingStatDaily.campaign_id,
                AdvertisingStatDaily.stat_date,
                AdvertisingStatDaily.nm_id,
                AdvertisingStatDaily.currency,
                func.sum(AdvertisingStatDaily.spend),
            )
            .where(
                AdvertisingStatDaily.nm_id.in_(owned),
                AdvertisingStatDaily.stat_date >= date_from,
                AdvertisingStatDaily.stat_date <= date_to,
            )
            .group_by(
                AdvertisingStatDaily.campaign_id,
                AdvertisingStatDaily.stat_date,
                AdvertisingStatDaily.nm_id,
                AdvertisingStatDaily.currency,
            )
        )
    ).all()
    spend = [
        AdCampaignSpend(int(cid), day, int(nm), Decimal(total))
        for cid, day, nm, _currency, total in spend_rows
        if total
    ]
    if not spend:
        return AdCampaignFacts(campaigns=[], spend=[], search=[], bonus=[])
    spend_labels = {str(currency or "") for *_key, currency, total in spend_rows if total}
    campaign_ids = sorted({row.campaign_id for row in spend})

    search_rows = (
        await session.execute(
            select(
                AdvertisingSearchStatDaily.campaign_id,
                AdvertisingSearchStatDaily.stat_date,
                func.sum(AdvertisingSearchStatDaily.spend),
            )
            .where(
                AdvertisingSearchStatDaily.nm_id.in_(owned),
                AdvertisingSearchStatDaily.stat_date >= date_from,
                AdvertisingSearchStatDaily.stat_date <= date_to,
            )
            .group_by(AdvertisingSearchStatDaily.campaign_id, AdvertisingSearchStatDaily.stat_date)
        )
    ).all()
    search = [
        AdCampaignSearch(int(cid), day, Decimal(total)) for cid, day, total in search_rows if total
    ]

    meta_rows = (
        await session.execute(
            select(
                Campaign.campaign_id,
                Campaign.payment_type,
                Campaign.bid_type,
                Campaign.placement_search,
                Campaign.placement_recommendations,
            ).where(Campaign.campaign_id.in_(campaign_ids))
        )
    ).all()
    campaigns = [
        AdCampaignMeta(int(cid), payment, bid, in_search, in_shelves)
        for cid, payment, bid, in_search, in_shelves in meta_rows
    ]

    ledger = await _ledger(session, campaign_ids=campaign_ids, date_from=date_from, date_to=date_to)
    bonus = await _scaled_bonus(
        session, spend=spend, ledger=ledger, date_from=date_from, date_to=date_to
    )
    # Rows from before the campaign label existed carry none; for those the
    # ledger's own label speaks — its bonus rows excepted, as in
    # `load_ad_currencies`, whose answer this must stay equal to.
    currencies = spend_labels - {""}
    if "" in spend_labels:
        currencies |= {
            row.currency
            for row in ledger
            if row.currency and row.payment_type not in BONUS_PAYMENT_TYPES
        }
    return AdCampaignFacts(
        campaigns=campaigns,
        spend=spend,
        search=search,
        bonus=bonus,
        currencies=tuple(sorted(currencies)),
        ledger_known=bool(ledger),
    )


class _LedgerRow(NamedTuple):
    campaign_id: int
    stat_date: date
    payment_type: str
    currency: str
    amount: Decimal


async def _ledger(
    session: AsyncSession, *, campaign_ids: list[int], date_from: date, date_to: date
) -> list[_LedgerRow]:
    """Every write-off of these campaigns in the window, whoever funded it.

    One read serves three answers — the bonus, whether the ledger covers the
    window at all, and the currencies it bills in — which used to be three
    passes over the same table.
    """
    rows = (
        await session.execute(
            select(
                AdvertisingWriteOffDaily.campaign_id,
                AdvertisingWriteOffDaily.stat_date,
                AdvertisingWriteOffDaily.payment_type,
                AdvertisingWriteOffDaily.currency,
                func.sum(AdvertisingWriteOffDaily.amount),
            )
            .where(
                AdvertisingWriteOffDaily.campaign_id.in_(campaign_ids),
                AdvertisingWriteOffDaily.stat_date >= date_from,
                AdvertisingWriteOffDaily.stat_date <= date_to,
            )
            .group_by(
                AdvertisingWriteOffDaily.campaign_id,
                AdvertisingWriteOffDaily.stat_date,
                AdvertisingWriteOffDaily.payment_type,
                AdvertisingWriteOffDaily.currency,
            )
        )
    ).all()
    return [
        _LedgerRow(int(cid), day, str(payment), str(currency or ""), Decimal(amount or 0))
        for cid, day, payment, currency, amount in rows
    ]


async def _scaled_bonus(
    session: AsyncSession,
    *,
    spend: list[AdCampaignSpend],
    ledger: list[_LedgerRow],
    date_from: date,
    date_to: date,
) -> list[AdCampaignBonus]:
    """Return the ledger's bonus rows, each scaled by the кабинет's share of its campaign.

    The share is taken over the window: the campaign's spend on this кабинет's
    cards over its spend on every card. For a campaign that only ever advertised
    this кабинет — every campaign seen on prod — it is exactly one.
    """
    charges: dict[tuple[int, date], Decimal] = {}
    for entry in ledger:
        if entry.payment_type in BONUS_PAYMENT_TYPES and entry.amount:
            key = (entry.campaign_id, entry.stat_date)
            charges[key] = charges.get(key, Decimal(0)) + entry.amount
    if not charges:
        return []

    charged = sorted({campaign_id for campaign_id, _day in charges})
    whole = {
        int(cid): Decimal(total)
        for cid, total in (
            await session.execute(
                select(AdvertisingStatDaily.campaign_id, func.sum(AdvertisingStatDaily.spend))
                .where(
                    AdvertisingStatDaily.campaign_id.in_(charged),
                    AdvertisingStatDaily.stat_date >= date_from,
                    AdvertisingStatDaily.stat_date <= date_to,
                )
                .group_by(AdvertisingStatDaily.campaign_id)
            )
        ).all()
        if total
    }
    mine: dict[int, Decimal] = {}
    for row in spend:
        mine[row.campaign_id] = mine.get(row.campaign_id, Decimal(0)) + row.spend

    out: list[AdCampaignBonus] = []
    for (campaign_id, day), amount in charges.items():
        total = whole.get(campaign_id)
        if not total:
            continue
        share = min(mine.get(campaign_id, Decimal(0)) / total, Decimal(1))
        scaled = (amount * share).quantize(_CENT)
        if scaled:
            out.append(AdCampaignBonus(campaign_id, day, scaled))
    return out
