"""Unit tests for the fake-harvest WB clients and their construction seam.

The synthetic clients let local development run the whole harvest pipeline
without spending WB's rate budget. Two properties are load-bearing and pinned
here: the factory swaps them in on ``wb_fake_harvest`` alone (so local and prod
share one code path), and their output is deterministic and shaped like the real
payloads (so it flows through ingestion into debuggable dashboard numbers).
"""

from __future__ import annotations

from datetime import date

from src.core.config import Settings
from src.integrations.wildberries import (
    WBAnalyticsClient,
    WBPricesClient,
    build_analytics_client,
    build_card_client,
    build_prices_client,
)
from src.integrations.wildberries.synthetic import (
    SyntheticAnalyticsClient,
    SyntheticPricesClient,
)

_WINDOW_START = date(2026, 7, 20)
_WINDOW_END = date(2026, 7, 22)


def _fake() -> Settings:
    """Settings with fake harvesting on (local default environment)."""
    return Settings(wb_fake_harvest=True)  # type: ignore[call-arg]


def _real() -> Settings:
    """Settings with fake harvesting off — the production behaviour."""
    return Settings(wb_fake_harvest=False)  # type: ignore[call-arg]


def test_factory_returns_synthetic_only_when_faking() -> None:
    """The flag alone decides real vs synthetic — the seam that keeps one code
    path across local and prod."""
    assert isinstance(build_analytics_client(_fake(), token="t"), SyntheticAnalyticsClient)
    assert isinstance(build_prices_client(_fake(), token="t", nm_ids=[1]), SyntheticPricesClient)

    real_analytics = build_analytics_client(_real(), token="t")
    real_prices = build_prices_client(_real(), token="t", nm_ids=[1])

    assert type(real_analytics) is WBAnalyticsClient
    assert type(real_prices) is WBPricesClient


async def test_synthetic_funnel_covers_every_day_per_sku() -> None:
    """One product node per SKU, each carrying a row for every day in-window."""
    async with build_analytics_client(_fake(), token="t") as client:
        rows = await client.fetch_sales_funnel(
            nm_ids=[101, 202], date_from=_WINDOW_START, date_to=_WINDOW_END
        )

    assert [row.nm_id for row in rows] == [101, 202]
    assert [day.stat_date for day in rows[0].history] == [
        date(2026, 7, 20),
        date(2026, 7, 21),
        date(2026, 7, 22),
    ]


async def test_synthetic_funnel_is_a_plausible_funnel() -> None:
    """Carts ≤ opens and orders ≤ carts, so the ingested funnel is not nonsense."""
    async with build_analytics_client(_fake(), token="t") as client:
        rows = await client.fetch_sales_funnel(
            nm_ids=[101], date_from=_WINDOW_START, date_to=_WINDOW_END
        )

    for day in rows[0].history:
        assert day.open_count >= day.cart_count >= day.order_count >= day.buyout_count


async def test_synthetic_output_is_deterministic() -> None:
    """The same SKU/day yields the same figures on every call.

    A moving synthetic series would be useless for debugging a chart — the whole
    point is a stable, reproducible dataset.
    """
    async with build_analytics_client(_fake(), token="t") as client:
        first = await client.fetch_sales_funnel(
            nm_ids=[101], date_from=_WINDOW_START, date_to=_WINDOW_END
        )
        second = await client.fetch_sales_funnel(
            nm_ids=[101], date_from=_WINDOW_START, date_to=_WINDOW_END
        )

    assert [d.order_count for d in first[0].history] == [d.order_count for d in second[0].history]


async def test_synthetic_customer_price_is_below_seller_price() -> None:
    """The storefront (customer) price sits under the seller price, so СПП is
    positive — the derived discount the dashboard shows must be non-negative."""
    nm_id = 101
    async with build_prices_client(_fake(), token="t", nm_ids=[nm_id]) as prices:
        seller = (await prices.fetch_prices())[0].seller_price
    async with build_card_client(_fake()) as card:
        customer = (await card.fetch_customer_prices([nm_id]))[0].customer_price

    assert seller is not None
    assert customer is not None
    assert 0 < customer < seller


async def test_synthetic_stock_lands_on_the_skus_real_sizes() -> None:
    """Stock rows carry the SKU's catalogued ``chrt_id``s, nothing invented.

    A stock row has no size label of its own — the detail view joins ``chrt_id``
    back to ``product_size`` to find one. Rows on invented ids therefore render
    as a bare characteristic id, which is a local-only difference from
    production that reads as a bug in the panel.
    """
    sizes = {101: [917310181, 917338406, 917338407]}

    async with build_analytics_client(_fake(), token="t", size_ids_by_nm=sizes) as client:
        rows = await client.fetch_warehouse_stocks(nm_ids=[101])

    assert rows
    assert {row.chrt_id for row in rows} <= set(sizes[101])


async def test_synthetic_stock_spans_every_warehouse() -> None:
    """Each warehouse gets rows, so the «Остатки по складам» panel has columns."""
    async with build_analytics_client(
        _fake(), token="t", size_ids_by_nm={101: [1, 2, 3, 4]}
    ) as client:
        rows = await client.fetch_warehouse_stocks(nm_ids=[101])

    assert {row.warehouse_name for row in rows} == {"Коледино", "Электросталь", "Казань"}


async def test_synthetic_stock_falls_back_for_an_uncatalogued_sku() -> None:
    """A SKU whose sizes are unknown still gets stock — unlabelled, correctly.

    The first harvest of a new account fetches stock before its cards land, so
    there is genuinely no size to name yet.
    """
    async with build_analytics_client(_fake(), token="t") as client:
        rows = await client.fetch_warehouse_stocks(nm_ids=[101])

    assert rows
    assert {row.chrt_id for row in rows} <= {10100, 10101, 10102}


async def test_synthetic_stock_is_deterministic() -> None:
    """The same SKU yields the same stock on every call — a moving snapshot
    would make the day-over-day comparison panel useless for debugging."""
    sizes = {101: [11, 22, 33]}

    async with build_analytics_client(_fake(), token="t", size_ids_by_nm=sizes) as client:
        first = await client.fetch_warehouse_stocks(nm_ids=[101])
        second = await client.fetch_warehouse_stocks(nm_ids=[101])

    assert [(r.chrt_id, r.warehouse_name, r.quantity) for r in first] == [
        (r.chrt_id, r.warehouse_name, r.quantity) for r in second
    ]


async def test_the_real_analytics_client_ignores_the_size_map() -> None:
    """``size_ids_by_nm`` is a synthetic-only crutch: a real stock response
    carries its own sizes, so the production client must not grow a dependency
    on the caller having looked them up."""
    client = build_analytics_client(_real(), token="t", size_ids_by_nm={101: [1, 2]})

    assert type(client) is WBAnalyticsClient


async def test_synthetic_cohort_is_empty() -> None:
    """No synthetic buyout cohorts: the real endpoint is catalogue-wide with no
    SKU filter, so a DB-free client has no basis to answer for specific SKUs."""
    async with build_analytics_client(_fake(), token="t") as client:
        rows = await client.fetch_funnel_cohort_day(day=_WINDOW_START)

    assert rows == []
