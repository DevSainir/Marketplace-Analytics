"""Rouble ad money converted to the кабинет's currency where it is stored.

WB moved the ad accounts from RUB to KGS on 2026-08-20; a KGS кабинет's
earlier spend, and WB's bonuses on it, are stored by WB in roubles. The sweep
converts them at the Bank of Russia rate of their own day — the rate WB itself
converts at — and the rules worth pinning are SQL: the latest rate on or before
the day, the кабинет read off its funnel, the ledger rows merging across the
currency key, and that a second run changes nothing.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import (
    AdvertisingSearchStatDaily,
    AdvertisingStatDaily,
    AdvertisingWriteOffDaily,
    CbrRate,
    ProductCard,
    SalesFunnelDaily,
)
from src.modules.monitoring.repos.ad_money import convert_rouble_ad_money

KGS_NM, RUB_NM, DELISTED_NM = 7001, 7002, 7003
KGS_CABINET = uuid.UUID("019f657a-0000-7000-8000-0000000c0001")
RUB_CABINET = uuid.UUID("019f657a-0000-7000-8000-0000000c0002")
#: Saturday 11.07.2026: 87.6681 ₽ per 100 с, so 1 ₽ = 1.140665… с. WB converted
#: Sunday 12.07 at exactly this rate.
SATURDAY, SUNDAY = date(2026, 7, 11), date(2026, 7, 12)


def _funnel(nm_id: int, currency: str) -> SalesFunnelDaily:
    return SalesFunnelDaily(
        stat_date=SATURDAY,
        nm_id=nm_id,
        open_count=10,
        cart_count=2,
        order_count=1,
        buyout_count=0,
        add_to_wishlist=0,
        cart_conversion=0,
        order_conversion=0,
        buyout_conversion=0,
        order_sum=Decimal("1140.67"),
        currency=currency,
    )


def _ad(
    nm_id: int, campaign_id: int, *, day: date = SUNDAY, currency: str = "RUB"
) -> AdvertisingStatDaily:
    return AdvertisingStatDaily(
        stat_date=day,
        campaign_id=campaign_id,
        app_type=1,
        nm_id=nm_id,
        views=100,
        clicks=5,
        add_to_cart=1,
        spend=Decimal("1000"),
        orders=1,
        order_sum=Decimal("4000"),
        currency=currency,
    )


async def _seed(session: AsyncSession) -> None:
    session.add_all(
        [
            CbrRate(
                currency="KGS", rate_date=date(2026, 7, 10), nominal=100, value=Decimal("86.8287")
            ),
            CbrRate(currency="KGS", rate_date=SATURDAY, nominal=100, value=Decimal("87.6681")),
            _funnel(KGS_NM, "KGS"),
            _funnel(RUB_NM, "RUB"),
            ProductCard(nm_id=KGS_NM, workspace_id=KGS_CABINET, vendor_code="kgs"),
            ProductCard(nm_id=RUB_NM, workspace_id=RUB_CABINET, vendor_code="rub"),
            # Delisted before WB valued the funnel: no currency of its own.
            ProductCard(nm_id=DELISTED_NM, workspace_id=KGS_CABINET, vendor_code="old"),
        ]
    )
    await session.flush()


async def _stat(session: AsyncSession, campaign_id: int) -> AdvertisingStatDaily:
    return (
        await session.execute(
            sa.select(AdvertisingStatDaily).where(AdvertisingStatDaily.campaign_id == campaign_id)
        )
    ).scalar_one()


async def test_a_rouble_day_takes_the_latest_rate_on_or_before_it(db_session: AsyncSession) -> None:
    await _seed(db_session)
    db_session.add(_ad(KGS_NM, 801))
    await db_session.flush()

    await convert_rouble_ad_money(db_session, campaign_ids=[801])
    db_session.expire_all()
    row = await _stat(db_session, 801)

    assert row.spend == Decimal("1140.67")
    assert row.order_sum == Decimal("4562.66")
    assert (row.currency, row.fx_from) == ("KGS", "RUB")
    assert round(row.fx_rate or 0, 5) == Decimal("1.14067")


async def test_a_second_sweep_changes_nothing(db_session: AsyncSession) -> None:
    await _seed(db_session)
    db_session.add(_ad(KGS_NM, 802))
    await db_session.flush()

    await convert_rouble_ad_money(db_session, campaign_ids=[802])
    again = await convert_rouble_ad_money(db_session, campaign_ids=[802])
    db_session.expire_all()

    assert again == 0
    assert (await _stat(db_session, 802)).spend == Decimal("1140.67")


async def test_an_unlabelled_row_before_the_switch_is_roubles(db_session: AsyncSession) -> None:
    """Every ad account billed in RUB until 20.08.2026; a blank label there is RUB."""
    await _seed(db_session)
    db_session.add(_ad(KGS_NM, 803, currency=""))
    await db_session.flush()

    await convert_rouble_ad_money(db_session, campaign_ids=[803])
    db_session.expire_all()

    assert (await _stat(db_session, 803)).currency == "KGS"


async def test_a_rouble_cabinet_keeps_its_roubles(db_session: AsyncSession) -> None:
    """An article whose funnel speaks RUB belongs to a кабинет that settles in RUB."""
    await _seed(db_session)
    db_session.add(_ad(RUB_NM, 804))
    await db_session.flush()

    converted = await convert_rouble_ad_money(db_session, campaign_ids=[804])
    db_session.expire_all()

    assert converted == 0
    assert (await _stat(db_session, 804)).spend == Decimal("1000")


async def test_a_day_with_no_rate_stays_in_roubles(db_session: AsyncSession) -> None:
    """Past the loaded rates nothing is guessed — the screens show «—» instead."""
    await _seed(db_session)
    db_session.add(_ad(KGS_NM, 805, day=date(2026, 9, 1)))
    await db_session.flush()

    await convert_rouble_ad_money(db_session, campaign_ids=[805])
    db_session.expire_all()

    assert (await _stat(db_session, 805)).currency == "RUB"


async def test_the_search_slice_of_a_rouble_campaign_follows_it(db_session: AsyncSession) -> None:
    await _seed(db_session)
    db_session.add_all(
        [
            _ad(KGS_NM, 806),
            AdvertisingSearchStatDaily(
                stat_date=SUNDAY, campaign_id=806, nm_id=KGS_NM, views=40, spend=Decimal("400")
            ),
        ]
    )
    await db_session.flush()

    await convert_rouble_ad_money(db_session, campaign_ids=[806])
    db_session.expire_all()
    search = (
        await db_session.execute(
            sa.select(AdvertisingSearchStatDaily).where(
                AdvertisingSearchStatDaily.campaign_id == 806
            )
        )
    ).scalar_one()

    assert search.spend == Decimal("456.27")


async def test_a_rouble_bonus_merges_into_the_days_som_row(db_session: AsyncSession) -> None:
    """20.08 split one document across both currencies; the ledger keys on currency."""
    await _seed(db_session)
    db_session.add_all(
        [
            _ad(KGS_NM, 807),
            AdvertisingWriteOffDaily(
                stat_date=SUNDAY,
                campaign_id=807,
                payment_type="Кэшбэк",
                currency="RUB",
                amount=Decimal("100"),
                write_offs=1,
            ),
            AdvertisingWriteOffDaily(
                stat_date=SUNDAY,
                campaign_id=807,
                payment_type="Кэшбэк",
                currency="KGS",
                amount=Decimal("50"),
                write_offs=2,
            ),
        ]
    )
    await db_session.flush()

    await convert_rouble_ad_money(db_session, campaign_ids=[807])
    db_session.expire_all()
    rows = (
        (
            await db_session.execute(
                sa.select(AdvertisingWriteOffDaily).where(
                    AdvertisingWriteOffDaily.campaign_id == 807
                )
            )
        )
        .scalars()
        .all()
    )

    assert [(r.currency, r.amount, r.write_offs) for r in rows] == [("KGS", Decimal("164.07"), 3)]


async def test_a_card_with_no_funnel_of_its_own_takes_its_cabinets_currency(
    db_session: AsyncSession,
) -> None:
    """A card delisted before WB served funnel sums still spent the кабинет's money."""
    await _seed(db_session)
    db_session.add(_ad(DELISTED_NM, 808))
    await db_session.flush()

    await convert_rouble_ad_money(db_session, campaign_ids=[808])
    db_session.expire_all()

    assert (await _stat(db_session, 808)).currency == "KGS"


async def test_the_new_year_gap_still_has_a_rate(db_session: AsyncSession) -> None:
    """The Bank publishes nothing from 28.12.2024 to 11.01.2025; 10.01 is still 28.12's."""
    db_session.add_all(
        [
            CbrRate(
                currency="KGS", rate_date=date(2024, 12, 28), nominal=10, value=Decimal("11.7")
            ),
            _funnel(KGS_NM, "KGS"),
            ProductCard(nm_id=KGS_NM, workspace_id=KGS_CABINET, vendor_code="kgs"),
            _ad(KGS_NM, 809, day=date(2025, 1, 10)),
        ]
    )
    await db_session.flush()

    await convert_rouble_ad_money(db_session, campaign_ids=[809])
    db_session.expire_all()

    assert (await _stat(db_session, 809)).spend == Decimal("854.70")
