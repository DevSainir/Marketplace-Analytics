"""Every cross-module monitoring loader answers for ONE workspace.

These loaders are the seam the finreports P&L reads monitoring through, and
four of them carried no tenant argument at all until 2026-08-27. The result was
not a theoretical gap: ``GET /pnl/skus`` built its «Итого» row by summing the
returned mappings, so one seller's totals included every other seller's orders
and advertising spend — a cross-tenant disclosure that also made the number
wrong.

Each test here seeds TWO workspaces with overlapping data and asserts the
loader sees only one of them. They live in the integration tier because what is
being tested is the SQL: the semijoin through ``product_card`` is the whole
mechanism, and a fake repository would assert nothing about it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.contract import (
    ad_coverage,
    funnel_coverage,
    load_ad_spend_by_nm,
    load_card_photos,
    load_orders_by_nm,
)
from src.modules.monitoring.models import AdvertisingStatDaily, ProductCard, SalesFunnelDaily
from src.modules.organizations.models import Organization
from src.modules.workspaces.models import Workspace

pytestmark = pytest.mark.integration

MINE = 111111111
THEIRS = 222222222

#: Name prefixes a cross-module loader is expected to use. Widened with
#: ``search_`` on 2026-09-05, when `search_workspace_cards` was added and this
#: guard could not see it — a loader that matches no prefix is not exempt from
#: taking a tenant, it is invisible to the check that says so.
_LOADER_PREFIXES = ("load_", "search_", "funnel_", "ad_", "stock_")

WINDOW_FROM = date(2026, 8, 1)
WINDOW_TO = date(2026, 8, 31)


async def _workspace(session: AsyncSession, name: str) -> Workspace:
    """Persist a workspace in its own organisation.

    Separate organisations rather than two workspaces in one, because that is
    the boundary that matters: these loaders are what one COMPANY's P&L reads.
    """
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


async def _photo(session: AsyncSession, nm_id: int, url: str) -> None:
    """Give an already-registered card its main photo."""
    card = await session.get(ProductCard, nm_id)
    assert card is not None
    card.photo_url = url
    await session.flush()


async def _funnel(session: AsyncSession, nm_id: int, day: date, orders: int) -> None:
    """One day of funnel history for a SKU."""
    session.add(
        SalesFunnelDaily(
            nm_id=nm_id,
            stat_date=day,
            open_count=0,
            cart_count=0,
            order_count=orders,
            buyout_count=0,
            add_to_wishlist=0,
        )
    )
    await session.flush()


async def _ad_day(session: AsyncSession, nm_id: int, day: date, spend: str) -> None:
    """One day of advertising spend for a SKU."""
    session.add(
        AdvertisingStatDaily(
            nm_id=nm_id,
            stat_date=day,
            campaign_id=1,
            app_type=1,
            views=0,
            clicks=0,
            spend=Decimal(spend),
            orders=0,
            add_to_cart=0,
        )
    )
    await session.flush()


async def _two_tenants(db_session: AsyncSession) -> tuple[Workspace, Workspace]:
    """Two workspaces in two organisations, each owning one SKU."""
    mine = await _workspace(db_session, "Мой")
    theirs = await _workspace(db_session, "Чужой")
    await _sku(db_session, mine, MINE)
    await _sku(db_session, theirs, THEIRS)
    return mine, theirs


async def test_orders_exclude_another_tenants_skus(db_session: AsyncSession) -> None:
    """The mapping the «Заказы» column is built from carries one seller only.

    Both SKUs have funnel rows in the same window, so an unscoped query returns
    both — which is exactly what the totals row used to sum.
    """
    mine, _ = await _two_tenants(db_session)
    await _funnel(db_session, MINE, date(2026, 8, 10), orders=7)
    await _funnel(db_session, THEIRS, date(2026, 8, 10), orders=900)

    orders = await load_orders_by_nm(
        db_session, workspace_id=mine.id, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    assert orders == {MINE: 7}


async def test_ad_spend_excludes_another_tenants_skus(db_session: AsyncSession) -> None:
    """Same for «Реклама», which is money and therefore louder when wrong."""
    mine, _ = await _two_tenants(db_session)
    await _ad_day(db_session, MINE, date(2026, 8, 10), "150.00")
    await _ad_day(db_session, THEIRS, date(2026, 8, 10), "99999.00")

    spend = await load_ad_spend_by_nm(
        db_session, workspace_id=mine.id, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    assert spend == {MINE: Decimal("150.00")}


async def test_funnel_coverage_reports_only_this_tenants_days(
    db_session: AsyncSession,
) -> None:
    """The coverage span is shown to the seller as «заказы известны с …».

    Unscoped, it would report the day ANOTHER seller's history begins — a
    smaller leak than the figures, and still a fact about someone else's
    account printed on this one's statement.
    """
    mine, _ = await _two_tenants(db_session)
    await _funnel(db_session, MINE, date(2026, 8, 20), orders=1)
    await _funnel(db_session, THEIRS, date(2026, 8, 2), orders=1)

    first, last = await funnel_coverage(
        db_session, workspace_id=mine.id, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    assert (first, last) == (date(2026, 8, 20), date(2026, 8, 20))


async def test_ad_coverage_reports_only_this_tenants_days(db_session: AsyncSession) -> None:
    """Same reasoning as the funnel span."""
    mine, _ = await _two_tenants(db_session)
    await _ad_day(db_session, MINE, date(2026, 8, 20), "10.00")
    await _ad_day(db_session, THEIRS, date(2026, 8, 2), "10.00")

    first, last = await ad_coverage(
        db_session, workspace_id=mine.id, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    assert (first, last) == (date(2026, 8, 20), date(2026, 8, 20))


async def test_card_photos_exclude_another_tenants_skus(db_session: AsyncSession) -> None:
    """The P&L's thumbnails carry one seller's catalogue only.

    A leak here is not a wrong number but a picture: another seller's product
    photo rendered next to your own article, on a page about your money. Both
    SKUs carry a photo, so an unscoped query returns both.
    """
    mine, _ = await _two_tenants(db_session)
    await _photo(db_session, MINE, "https://basket-44.wbbasket.ru/vol1/images/big/1.webp")
    await _photo(db_session, THEIRS, "https://basket-44.wbbasket.ru/vol2/images/big/1.webp")

    photos = await load_card_photos(db_session, workspace_id=mine.id)

    assert photos == {MINE: "https://basket-44.wbbasket.ru/vol1/images/big/1.webp"}


async def test_a_card_without_a_photo_is_absent_rather_than_blank(
    db_session: AsyncSession,
) -> None:
    """A photo-less card yields no key, so callers read ``.get()`` as "no photo".

    The column is non-nullable and defaults to "", so an unfiltered query would
    hand every caller an empty string to special-case instead.
    """
    mine, _ = await _two_tenants(db_session)

    assert await load_card_photos(db_session, workspace_id=mine.id) == {}


async def test_a_tenant_with_no_data_gets_nothing_rather_than_everything(
    db_session: AsyncSession,
) -> None:
    """The failure mode an unscoped query hides best.

    A brand-new workspace has no SKUs at all, so an unscoped loader returns the
    whole platform's history and the new tenant's very first P&L is somebody
    else's. Empty is the correct answer.
    """
    _, _ = await _two_tenants(db_session)
    await _funnel(db_session, THEIRS, date(2026, 8, 10), orders=900)
    await _ad_day(db_session, THEIRS, date(2026, 8, 10), "99999.00")
    empty = await _workspace(db_session, "Новый")

    orders = await load_orders_by_nm(
        db_session, workspace_id=empty.id, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )
    spend = await load_ad_spend_by_nm(
        db_session, workspace_id=empty.id, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    assert orders == {}
    assert spend == {}


async def test_an_unregistered_sku_belongs_to_nobody(db_session: AsyncSession) -> None:
    """Funnel rows whose SKU is not in ``product_card`` reach no tenant.

    They exist — a harvest can write a fact for a SKU whose card sync failed —
    and the semijoin is what keeps such an orphan out of everyone's statement
    rather than putting it in the first one that asks.
    """
    mine, _ = await _two_tenants(db_session)
    await _funnel(db_session, 999999999, date(2026, 8, 10), orders=42)

    orders = await load_orders_by_nm(
        db_session, workspace_id=mine.id, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    assert 999999999 not in orders


async def test_the_window_still_bounds_a_scoped_query(db_session: AsyncSession) -> None:
    """Scoping must not have replaced the date filter, only joined it."""
    mine, _ = await _two_tenants(db_session)
    await _funnel(db_session, MINE, date(2026, 8, 10), orders=7)
    await _funnel(db_session, MINE, date(2026, 7, 1), orders=500)

    orders = await load_orders_by_nm(
        db_session, workspace_id=mine.id, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )

    assert orders == {MINE: 7}


def test_every_export_loader_demands_a_workspace() -> None:
    """No loader in the contract may be callable without a tenant.

    A belt to the braces above: the four fixed here leaked precisely because
    their signatures allowed a caller not to say whose data it wanted. This
    fails the build if a new one is added the same way, or an existing one is
    given a default.
    """
    import inspect

    from src.modules.monitoring import contract

    scoped = [
        name
        for name in contract.__all__
        if name.startswith(_LOADER_PREFIXES) and callable(getattr(contract, name))
    ]
    assert scoped, "the loaders moved; this guard needs re-pointing"

    for name in scoped:
        signature = inspect.signature(getattr(contract, name))
        parameter = signature.parameters.get("workspace_id")
        assert parameter is not None, f"{name} takes no workspace_id"
        assert parameter.default is inspect.Parameter.empty, (
            f"{name}'s workspace_id has a default; a caller can omit it"
        )
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"{name}'s workspace_id is positional; it can be passed by accident"
        )


def test_the_loader_signature_guard_actually_has_something_to_check() -> None:
    """Pin the count, so a loader silently disappearing is not a silent pass."""
    from src.modules.monitoring import contract

    scoped = [
        name
        for name in contract.__all__
        if name.startswith(_LOADER_PREFIXES) and callable(getattr(contract, name))
    ]

    # 11 since 2026-09-05: `load_workspace_card` and `search_workspace_cards`
    # back the A/B article picker, and both take the tenant because WB article
    # numbers are global — "does this article exist" and "does it belong to the
    # caller" are different questions and only the second is safe to act on.
    #
    # 12 since 2026-09-09: `load_card_photos` gives the P&L its SKU thumbnails.
    # It is scoped on `product_card.workspace_id`, the same registry column
    # `load_vendor_codes` uses, and `test_card_photos_exclude_another_tenants_skus`
    # is what actually proves it — this count only forces somebody to look.
    #
    # Bumping this number is the deliberate step that says a new cross-module
    # loader was reviewed for tenancy, which the four unscoped loaders of August
    # never were.
    assert len(scoped) == 15, f"expected 15 scoped loaders, found {sorted(scoped)}"
