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

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import (
    AdvertisingStatDaily,
    AdvertisingWriteOffDaily,
    ProductCard,
)
from src.modules.monitoring.models.prices import PriceSnapshot
from src.modules.monitoring.repos import AdvertisingWriteOffRepository, PriceRepository


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


def _ad_row(day: date, *, campaign_id: int, nm_id: int) -> AdvertisingStatDaily:
    return AdvertisingStatDaily(
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
