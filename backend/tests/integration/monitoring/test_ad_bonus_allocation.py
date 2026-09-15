"""How WB's advertising bonus is split back onto SKUs.

WB's write-off ledger has no ``nmId`` — a charge belongs to a campaign — so the
per-SKU «Бонусы» column is an allocation, and this is where its rules are
pinned. It lives in the integration tier because the rules ARE the SQL: the
proportional split, the currency partition and the workspace semijoin are all
expressed in the query, and a fake repository would assert none of them.

The numbers are the live 2026-09-01..15 shape of the `Демо` workspace, where
WB funded 123 291 of 392 003 KGS of write-offs.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.contract import (
    ad_bonus_currencies,
    ad_bonus_unknown_types,
    load_ad_bonus_by_nm,
)
from src.modules.monitoring.models import (
    AdvertisingStatDaily,
    AdvertisingWriteOffDaily,
    ProductCard,
)
from src.modules.organizations.models import Organization
from src.modules.workspaces.models import Workspace

pytestmark = pytest.mark.integration

MINE = 995716075
ALSO_MINE = 953770957
THEIRS = 222222222
CAMPAIGN = 97455888
WINDOW_FROM = date(2026, 9, 1)
WINDOW_TO = date(2026, 9, 15)


async def _workspace(session: AsyncSession, name: str) -> Workspace:
    """Persist a workspace in its own organisation."""
    org = Organization(name=f"Орг {name}", is_primary=False)
    session.add(org)
    await session.flush()
    workspace = Workspace(organization_id=org.id, name=name)
    session.add(workspace)
    await session.flush()
    return workspace


async def _sku(session: AsyncSession, workspace: Workspace, nm_id: int) -> None:
    """Register a SKU to a workspace — the registry every scope query joins."""
    session.add(ProductCard(nm_id=nm_id, workspace_id=workspace.id, vendor_code=f"A-{nm_id}"))
    await session.flush()


async def _spend(
    session: AsyncSession,
    nm_id: int,
    spend: str,
    *,
    campaign_id: int = CAMPAIGN,
    day: date = date(2026, 9, 5),
) -> None:
    """One campaign-day of fullstats spend booked on a SKU."""
    session.add(
        AdvertisingStatDaily(
            nm_id=nm_id,
            stat_date=day,
            campaign_id=campaign_id,
            app_type=1,
            views=0,
            clicks=0,
            add_to_cart=0,
            spend=Decimal(spend),
            orders=0,
            order_sum=Decimal("0"),
        )
    )
    await session.flush()


async def _write_off(
    session: AsyncSession,
    amount: str,
    *,
    campaign_id: int = CAMPAIGN,
    payment_type: str = "Кэшбэк",
    currency: str = "KGS",
    day: date = date(2026, 9, 5),
) -> None:
    """One day's charge for one campaign from one funding source."""
    session.add(
        AdvertisingWriteOffDaily(
            stat_date=day,
            campaign_id=campaign_id,
            payment_type=payment_type,
            currency=currency,
            amount=Decimal(amount),
            write_offs=1,
        )
    )
    await session.flush()


async def _load(session: AsyncSession, workspace: Workspace) -> dict[int, Decimal]:
    """Run the loader over the standard window."""
    return await load_ad_bonus_by_nm(
        session, workspace_id=workspace.id, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )


async def test_the_bonus_splits_across_a_campaigns_skus_by_their_spend(
    db_session: AsyncSession,
) -> None:
    """A campaign advertises several cards; its bonus follows the money."""
    mine = await _workspace(db_session, "Мой")
    await _sku(db_session, mine, MINE)
    await _sku(db_session, mine, ALSO_MINE)
    await _spend(db_session, MINE, "750")
    await _spend(db_session, ALSO_MINE, "250")
    await _write_off(db_session, "400")

    assert await _load(db_session, mine) == {MINE: Decimal("300"), ALSO_MINE: Decimal("100")}


async def test_only_the_bonus_funding_types_are_deducted(db_session: AsyncSession) -> None:
    """«Баланс» is the seller's own money and must never lower a cost.

    The single most expensive way to get this wrong: subtracting real spend
    overstates profit, and nothing downstream contradicts it.
    """
    mine = await _workspace(db_session, "Мой")
    await _sku(db_session, mine, MINE)
    await _spend(db_session, MINE, "1000")
    await _write_off(db_session, "600", payment_type="Баланс")
    await _write_off(db_session, "150", payment_type="Кэшбэк")

    assert await _load(db_session, mine) == {MINE: Decimal("150")}


async def test_an_unknown_funding_label_is_treated_as_the_sellers_money(
    db_session: AsyncSession,
) -> None:
    """The match is an allowlist: a WB rename degrades to today's behaviour.

    And it is reported, so the silent fallback is audible — the caveat is the
    only thing standing between a rename and a number nobody questions.
    """
    mine = await _workspace(db_session, "Мой")
    await _sku(db_session, mine, MINE)
    await _spend(db_session, MINE, "1000")
    await _write_off(db_session, "400", payment_type="Промо-баллы")

    assert await _load(db_session, mine) == {}
    assert await ad_bonus_unknown_types(
        db_session, workspace_id=mine.id, date_from=WINDOW_FROM, date_to=WINDOW_TO
    ) == ["Промо-баллы"]


async def test_a_relabelled_currency_still_reaches_the_spend_it_came_off(
    db_session: AsyncSession,
) -> None:
    """WB relabelled the advertising account RUB -> KGS on 2026-08-20.

    The amounts did not change with the label — `upd` agrees with `fullstats`
    at 90-100 % per campaign on BOTH sides of it — because both come from the
    same advertising account. Filtering the ledger by the SETTLEMENT currency
    was this loader's first shape and it dropped 402 022 of real bonuses for
    every window spanning the relabel.
    """
    mine = await _workspace(db_session, "Мой")
    await _sku(db_session, mine, MINE)
    await _spend(db_session, MINE, "1000")
    await _write_off(db_session, "300", currency="KGS")
    await _write_off(db_session, "50", currency="RUB")

    assert await _load(db_session, mine) == {MINE: Decimal("350")}
    assert await ad_bonus_currencies(
        db_session, workspace_id=mine.id, date_from=WINDOW_FROM, date_to=WINDOW_TO
    ) == ["KGS", "RUB"]


async def test_a_bonus_never_exceeds_the_spend_it_belongs_to(db_session: AsyncSession) -> None:
    """A charge dated inside the window whose impressions fell outside it.

    Unclamped, that prints a negative advertising cost and an invented profit.
    """
    mine = await _workspace(db_session, "Мой")
    await _sku(db_session, mine, MINE)
    await _spend(db_session, MINE, "100")
    await _write_off(db_session, "900")

    assert await _load(db_session, mine) == {MINE: Decimal("100")}


async def test_a_bonus_never_crosses_from_one_campaign_to_another(
    db_session: AsyncSession,
) -> None:
    """A campaign's bonus reaches only the SKUs that campaign advertised."""
    mine = await _workspace(db_session, "Мой")
    await _sku(db_session, mine, MINE)
    await _sku(db_session, mine, ALSO_MINE)
    await _spend(db_session, MINE, "1000", campaign_id=CAMPAIGN)
    await _spend(db_session, ALSO_MINE, "1000", campaign_id=97455887)
    await _write_off(db_session, "400", campaign_id=CAMPAIGN)

    assert await _load(db_session, mine) == {MINE: Decimal("400")}


async def test_another_tenants_share_is_dropped_not_redistributed(
    db_session: AsyncSession,
) -> None:
    """The denominator is the campaign's WHOLE spend, deliberately.

    Scoping the denominator to the asking workspace would hand it the other
    tenant's share of the bonus as well — a wrong number built out of a tenancy
    leak, which is the pair of failures this loader family already had once.
    """
    mine = await _workspace(db_session, "Мой")
    theirs = await _workspace(db_session, "Чужой")
    await _sku(db_session, mine, MINE)
    await _sku(db_session, theirs, THEIRS)
    await _spend(db_session, MINE, "500")
    await _spend(db_session, THEIRS, "500")
    await _write_off(db_session, "400")

    assert await _load(db_session, mine) == {MINE: Decimal("200")}


async def test_a_bonus_for_a_campaign_with_no_spend_rows_is_dropped(
    db_session: AsyncSession,
) -> None:
    """There is no SKU to land it on, and inventing one is worse than omitting.

    Happens when the ledger is backfilled further than fullstats has been.
    """
    mine = await _workspace(db_session, "Мой")
    await _sku(db_session, mine, MINE)
    await _write_off(db_session, "400")

    assert await _load(db_session, mine) == {}


async def test_the_window_bounds_the_ledger(db_session: AsyncSession) -> None:
    """A charge outside the reported window belongs to another period's report."""
    mine = await _workspace(db_session, "Мой")
    await _sku(db_session, mine, MINE)
    await _spend(db_session, MINE, "1000")
    await _write_off(db_session, "400", day=date(2026, 8, 20))

    assert await _load(db_session, mine) == {}
