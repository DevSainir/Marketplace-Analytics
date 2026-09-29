"""The two units a SKU's money is in, as the detail view reads them.

A кабинет that settles in KGS still has its prices in RUB and its campaigns in
whatever currency each was created in — the ad account moved RUB -> KGS on
2026-08-20 and older campaigns kept billing in RUB. The monitoring table labels
its rows from these two reads, so each is pinned against a real database: the
filters that keep a neighbour's campaign or an out-of-window day out of the
label are SQL, not Python.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.integrations.wildberries.schemas import WBFunnelAggregateRow, WBFunnelHistoryRow
from src.modules.monitoring.contract import load_ad_currencies
from src.modules.monitoring.models import (
    AdvertisingStatDaily,
    AdvertisingWriteOffDaily,
    ProductCard,
    SalesFunnelDaily,
)
from src.modules.monitoring.models.prices import PriceSnapshot
from src.modules.monitoring.repos import (
    AdvertisingRepository,
    AdvertisingWriteOffRepository,
    FunnelRepository,
    PriceRepository,
)
from src.modules.monitoring.services.ingestion.funnel import FunnelIngestion


def _write_off(
    day: date, campaign_id: int, currency: str, payment_type: str = "Баланс"
) -> AdvertisingWriteOffDaily:
    return AdvertisingWriteOffDaily(
        stat_date=day,
        campaign_id=campaign_id,
        payment_type=payment_type,
        currency=currency,
        amount=Decimal("100"),
        write_offs=1,
    )


def _ad_row(day: date, *, campaign_id: int, nm_id: int, currency: str = "") -> AdvertisingStatDaily:
    return AdvertisingStatDaily(
        currency=currency,
        stat_date=day,
        campaign_id=campaign_id,
        app_type=1,
        nm_id=nm_id,
        views=100,
        clicks=5,
        add_to_cart=1,
        spend=Decimal("50"),
        orders=1,
        order_sum=Decimal("4000"),
    )


async def test_an_old_window_takes_the_price_unit_from_the_newest_labelled_snapshot(
    db_session: AsyncSession,
) -> None:
    """Snapshots from before the label existed are blank; the newest label answers for them."""
    db_session.add_all(
        [
            PriceSnapshot(stat_date=date(2026, 9, 1), nm_id=3001, seller_price=4000, currency=""),
            PriceSnapshot(
                stat_date=date(2026, 9, 29), nm_id=3001, seller_price=4100, currency="RUB"
            ),
            PriceSnapshot(stat_date=date(2026, 9, 30), nm_id=3001, seller_price=4200, currency=""),
        ]
    )
    await db_session.flush()

    currency = await PriceRepository(db_session).currency_for_sku(nm_id=3001)

    assert currency == "RUB"


async def test_a_sku_never_priced_with_a_label_has_no_price_unit(db_session: AsyncSession) -> None:
    """No label is reported as unknown rather than guessed."""
    db_session.add(
        PriceSnapshot(stat_date=date(2026, 9, 1), nm_id=3002, seller_price=1, currency="")
    )
    await db_session.flush()

    currency = await PriceRepository(db_session).currency_for_sku(nm_id=3002)

    assert currency == ""


async def test_a_window_across_the_switch_names_both_ad_units(db_session: AsyncSession) -> None:
    """A RUB campaign before 20.08 and a KGS one after it: the window's spend is in two units."""
    db_session.add_all(
        [
            _write_off(date(2026, 8, 19), 501, "RUB"),
            _write_off(date(2026, 8, 25), 502, "KGS"),
        ]
    )
    await db_session.flush()

    currencies = await AdvertisingWriteOffRepository(db_session).currencies_for_campaigns(
        campaign_ids=[501, 502], date_from=date(2026, 8, 15), date_to=date(2026, 8, 31)
    )

    assert currencies == ["KGS", "RUB"]


async def test_the_ad_unit_ignores_other_campaigns_and_other_days(db_session: AsyncSession) -> None:
    """Only the SKU's own campaigns inside the window decide its label; a bonus row counts."""
    db_session.add_all(
        [
            _write_off(date(2026, 9, 10), 601, "KGS", payment_type="Кэшбэк"),
            _write_off(date(2026, 9, 10), 699, "RUB"),  # somebody else's campaign
            _write_off(date(2026, 8, 1), 601, "RUB"),  # before the window
        ]
    )
    await db_session.flush()

    currencies = await AdvertisingWriteOffRepository(db_session).currencies_for_campaigns(
        campaign_ids=[601], date_from=date(2026, 9, 1), date_to=date(2026, 9, 30)
    )

    assert currencies == ["KGS"]


async def test_a_sku_outside_the_ledger_takes_its_cabinets_ad_unit(
    db_session: AsyncSession,
) -> None:
    """The ledger names some campaigns only; the SKU's кабинет answers for the rest.

    On «Демо» 8 of the 31 campaigns that spent in a fortnight of September
    2026 had a write-off row — without the fallback most SKUs printed spend with
    no unit. A neighbour's campaign must not leak into the answer.
    """
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    db_session.add_all(
        [
            ProductCard(nm_id=4001, workspace_id=mine, vendor_code="LEDGERED"),
            ProductCard(nm_id=4002, workspace_id=mine, vendor_code="UNLEDGERED"),
            ProductCard(nm_id=4003, workspace_id=theirs, vendor_code="NEIGHBOUR"),
            _ad_row(date(2026, 9, 10), campaign_id=701, nm_id=4001),
            _ad_row(date(2026, 9, 10), campaign_id=702, nm_id=4002),
            _ad_row(date(2026, 9, 10), campaign_id=799, nm_id=4003),
            _write_off(date(2026, 9, 10), 701, "KGS"),
            _write_off(date(2026, 9, 10), 799, "RUB"),
        ]
    )
    await db_session.flush()

    currencies = await AdvertisingWriteOffRepository(db_session).currencies_for_sku_cabinet(
        nm_id=4002, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30)
    )

    assert currencies == ["KGS"]


# --------------------------------------------------------------------------- #
# The funnel's own money — in the settlement currency, owned per column
# --------------------------------------------------------------------------- #
def _history(nm_id: int, day: date, *, order_sum: float, buyout_sum: float) -> WBFunnelHistoryRow:
    return WBFunnelHistoryRow.model_validate(
        {
            "product": {"nmId": nm_id},
            "currency": "KGS",
            "history": [
                {
                    "date": day.isoformat(),
                    "orderCount": 2,
                    "orderSum": order_sum,
                    "buyoutCount": 0,
                    "buyoutSum": buyout_sum,
                }
            ],
        }
    )


def _aggregate(nm_id: int, *, order_sum: float, buyout_sum: float, cancel_sum: float) -> Any:
    return WBFunnelAggregateRow.model_validate(
        {
            "product": {"nmId": nm_id},
            "currency": "KGS",
            "statistic": {
                "selected": {
                    "orderCount": 2,
                    "orderSum": order_sum,
                    "buyoutCount": 1,
                    "buyoutSum": buyout_sum,
                    "cancelCount": 1,
                    "cancelSum": cancel_sum,
                }
            },
        }
    )


async def _funnel_row(session: AsyncSession, nm_id: int, day: date) -> SalesFunnelDaily:
    return (
        await session.execute(
            sa.select(SalesFunnelDaily).where(
                SalesFunnelDaily.nm_id == nm_id, SalesFunnelDaily.stat_date == day
            )
        )
    ).scalar_one()


async def test_the_daily_feed_stores_the_order_value_in_the_units_wb_states(
    db_session: AsyncSession,
) -> None:
    """The funnel's order sum lands with its unit — KGS, not the prices' RUB."""
    ingestion = FunnelIngestion(FunnelRepository(db_session))

    await ingestion.ingest_sales_funnel(
        [_history(5001, date(2026, 9, 27), order_sum=8209.32, buyout_sum=0)]
    )

    row = await _funnel_row(db_session, 5001, date(2026, 9, 27))
    assert row.order_sum == Decimal("8209.32")
    assert row.currency == "KGS"


async def test_a_later_daily_harvest_does_not_walk_a_matured_buyout_sum_back(
    db_session: AsyncSession,
) -> None:
    """Buyouts mature for weeks; the 7-day feed's figure must not undo the cohort's.

    Same ownership as ``buyout_count``: the history feed seeds a new day, the
    cohort pass owns it from then on.
    """
    ingestion = FunnelIngestion(FunnelRepository(db_session))
    day = date(2026, 9, 20)
    await ingestion.ingest_sales_funnel([_history(5002, day, order_sum=8000, buyout_sum=0)])
    await ingestion.ingest_funnel_cohorts(
        day, [_aggregate(5002, order_sum=8000, buyout_sum=4000, cancel_sum=4000)]
    )

    await ingestion.ingest_sales_funnel([_history(5002, day, order_sum=8000, buyout_sum=0)])

    row = await _funnel_row(db_session, 5002, day)
    assert row.buyout_sum == Decimal("4000")
    assert row.cancel_sum == Decimal("4000")


async def test_the_cohort_pass_fills_the_money_of_a_day_harvested_without_it(
    db_session: AsyncSession,
) -> None:
    """A row from before the sums were stored gets them from the aggregate.

    This is what the backfill relies on to fill a year of history without a
    second walk: the aggregate call it already makes for the cohort carries
    the day's money too.
    """
    day = date(2026, 6, 1)
    db_session.add(
        SalesFunnelDaily(
            stat_date=day,
            nm_id=5003,
            open_count=10,
            cart_count=3,
            order_count=2,
            buyout_count=1,
            cancel_count=1,
            add_to_wishlist=0,
            cart_conversion=30,
            order_conversion=66.67,
            buyout_conversion=50,
        )
    )
    await db_session.flush()

    await FunnelIngestion(FunnelRepository(db_session)).ingest_funnel_cohorts(
        day, [_aggregate(5003, order_sum=9640, buyout_sum=4820, cancel_sum=4820)]
    )

    row = await _funnel_row(db_session, 5003, day)
    assert row.order_sum == Decimal("9640")
    assert row.currency == "KGS"


# --------------------------------------------------------------------------- #
# Labelling spend harvested before its currency was stored
# --------------------------------------------------------------------------- #
async def test_only_this_workspaces_unlabelled_campaigns_are_asked_about(
    db_session: AsyncSession,
) -> None:
    """Each comes with its last stored day — the day a probe must include."""
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    db_session.add_all(
        [
            ProductCard(nm_id=6001, workspace_id=mine, vendor_code="MINE"),
            ProductCard(nm_id=6002, workspace_id=theirs, vendor_code="THEIRS"),
            _ad_row(date(2026, 8, 1), campaign_id=801, nm_id=6001),
            _ad_row(date(2026, 8, 9), campaign_id=801, nm_id=6001),
            _ad_row(date(2026, 9, 1), campaign_id=802, nm_id=6001, currency="KGS"),
            _ad_row(date(2026, 8, 5), campaign_id=899, nm_id=6002),
        ]
    )
    await db_session.flush()

    missing = await AdvertisingRepository(db_session).campaigns_without_currency(workspace_id=mine)

    assert missing == {801: date(2026, 8, 9)}


async def test_labelling_a_campaign_leaves_what_wb_already_said_alone(
    db_session: AsyncSession,
) -> None:
    """Blank rows take the campaign's currency; a labelled row keeps its own."""
    mine = uuid.uuid4()
    db_session.add_all(
        [
            ProductCard(nm_id=6101, workspace_id=mine, vendor_code="MINE"),
            _ad_row(date(2026, 8, 1), campaign_id=811, nm_id=6101),
            _ad_row(date(2026, 8, 2), campaign_id=811, nm_id=6101),
            _ad_row(date(2026, 9, 28), campaign_id=811, nm_id=6101, currency="XXX"),
        ]
    )
    await db_session.flush()

    labelled = await AdvertisingRepository(db_session).label_campaign_currency(
        workspace_id=mine, campaign_id=811, currency="RUB"
    )

    assert labelled == 2
    stored = (
        await db_session.execute(
            sa.select(AdvertisingStatDaily.stat_date, AdvertisingStatDaily.currency)
            .where(AdvertisingStatDaily.campaign_id == 811)
            .order_by(AdvertisingStatDaily.stat_date)
        )
    ).all()
    assert [currency for _, currency in stored] == ["RUB", "RUB", "XXX"]


async def test_a_window_half_labelled_names_the_ledgers_unit_as_well(
    db_session: AsyncSession,
) -> None:
    """While the backfill has not reached old rows, the label is the union.

    New rows say KGS; an old RUB campaign's rows are still blank and only the
    ledger knows them — the label must say both rather than KGS alone.
    """
    mine = uuid.uuid4()
    db_session.add_all(
        [
            ProductCard(nm_id=6201, workspace_id=mine, vendor_code="MINE"),
            _ad_row(date(2026, 8, 19), campaign_id=821, nm_id=6201),
            _ad_row(date(2026, 8, 25), campaign_id=822, nm_id=6201, currency="KGS"),
            _write_off(date(2026, 8, 19), 821, "RUB"),
        ]
    )
    await db_session.flush()

    currencies = await load_ad_currencies(
        db_session, workspace_id=mine, date_from=date(2026, 8, 15), date_to=date(2026, 8, 31)
    )

    assert currencies == ["KGS", "RUB"]
