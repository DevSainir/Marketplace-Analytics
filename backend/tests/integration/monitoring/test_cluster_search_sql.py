"""The «Поиск по кластерам» reads, against a real database.

These cannot go lower: each is a property of the SQL itself — the per-SKU
predicate, the weighted-mean `CASE`, the composite-key upsert and the campaign
sweep. A fake repository would assert nothing but its own arithmetic.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.repos.advertising_clusters import AdvertisingClusterRepository

MINE = 4001
OTHER_SKU = 4002

DAY_1 = date(2026, 8, 10)
DAY_2 = date(2026, 8, 11)
WINDOW = (date(2026, 8, 1), date(2026, 8, 13))
CAMPAIGN = 63214674


def _row(
    *,
    nm_id: int,
    cluster: str,
    day: date = DAY_1,
    campaign_id: int = CAMPAIGN,
    views: int = 100,
    clicks: int = 5,
    orders: int = 1,
    spend: float = 25.0,
    add_to_cart: int = 2,
    avg_position: float = 0.0,
) -> dict[str, object]:
    """One per-cluster daily row as ingestion would submit it."""
    return {
        "stat_date": day,
        "campaign_id": campaign_id,
        "nm_id": nm_id,
        "cluster": cluster,
        "views": views,
        "clicks": clicks,
        "add_to_cart": add_to_cart,
        "spend": spend,
        "orders": orders,
        "avg_position": avg_position,
    }


async def test_only_the_asked_for_skus_clusters_are_returned(db_session: AsyncSession) -> None:
    """The block is per-SKU, and two SKUs routinely share a cluster.

    Without the predicate a SKU's page would report the account's traffic for the
    phrase as its own — inflating exactly the number a bid decision rests on.
    """
    repo = AdvertisingClusterRepository(db_session)
    await repo.upsert_many(
        [
            _row(nm_id=MINE, cluster="носки мужские", views=100),
            _row(nm_id=OTHER_SKU, cluster="носки мужские", views=900),
        ]
    )
    await db_session.flush()

    found = await repo.aggregate_for_sku(
        nm_id=MINE, date_from=WINDOW[0], date_to=WINDOW[1], limit=50
    )

    assert [(row.cluster, row.views) for row in found] == [("носки мужские", 100)]


async def test_a_clusters_totals_are_summed_across_its_days_and_campaigns(
    db_session: AsyncSession,
) -> None:
    """One row per phrase: the seller asks about the cluster, not about its cells."""
    repo = AdvertisingClusterRepository(db_session)
    await repo.upsert_many(
        [
            _row(nm_id=MINE, cluster="носки", day=DAY_1, views=100, clicks=5, spend=25.0),
            _row(nm_id=MINE, cluster="носки", day=DAY_2, views=200, clicks=9, spend=40.0),
            _row(
                nm_id=MINE,
                cluster="носки",
                day=DAY_2,
                campaign_id=999,
                views=50,
                clicks=1,
                spend=10.0,
            ),
        ]
    )
    await db_session.flush()

    (aggregate,) = await repo.aggregate_for_sku(
        nm_id=MINE, date_from=WINDOW[0], date_to=WINDOW[1], limit=50
    )

    assert aggregate.views == 350
    assert aggregate.clicks == 15
    assert aggregate.spend == 75.0
    assert aggregate.days_count == 2
    assert aggregate.campaign_count == 2


async def test_clusters_are_ranked_by_impressions(db_session: AsyncSession) -> None:
    """Impressions are the cluster's real weight in the SKU's paid traffic."""
    repo = AdvertisingClusterRepository(db_session)
    await repo.upsert_many(
        [
            _row(nm_id=MINE, cluster="носки короткие", views=50),
            _row(nm_id=MINE, cluster="носки мужские", views=900),
        ]
    )
    await db_session.flush()

    found = await repo.aggregate_for_sku(
        nm_id=MINE, date_from=WINDOW[0], date_to=WINDOW[1], limit=50
    )

    assert [row.cluster for row in found] == ["носки мужские", "носки короткие"]


async def test_days_outside_the_window_are_excluded(db_session: AsyncSession) -> None:
    """The block follows the page's period selector, so the window must bite."""
    repo = AdvertisingClusterRepository(db_session)
    await repo.upsert_many(
        [
            _row(nm_id=MINE, cluster="носки", day=DAY_1, views=100),
            _row(nm_id=MINE, cluster="носки", day=date(2026, 7, 1), views=5000),
        ]
    )
    await db_session.flush()

    (aggregate,) = await repo.aggregate_for_sku(
        nm_id=MINE, date_from=WINDOW[0], date_to=WINDOW[1], limit=50
    )

    assert aggregate.views == 100


async def test_the_average_position_is_weighted_and_ignores_unreported_rows(
    db_session: AsyncSession,
) -> None:
    """The weighting lives in the SQL (a CASE), so it is pinned against Postgres.

    Rows WB gave no position for are excluded from both sides of the mean; a
    naive `avg()` over them would report a top-of-page ranking that never was.
    """
    repo = AdvertisingClusterRepository(db_session)
    await repo.upsert_many(
        [
            _row(nm_id=MINE, cluster="носки", day=DAY_1, views=1000, avg_position=3.0),
            _row(nm_id=MINE, cluster="носки", day=DAY_2, views=10, avg_position=40.0),
            _row(
                nm_id=MINE,
                cluster="носки",
                day=DAY_2,
                campaign_id=999,
                views=5000,
                avg_position=0.0,
            ),
        ]
    )
    await db_session.flush()

    (aggregate,) = await repo.aggregate_for_sku(
        nm_id=MINE, date_from=WINDOW[0], date_to=WINDOW[1], limit=50
    )

    assert aggregate.avg_position is not None
    assert round(aggregate.avg_position, 4) == round((3.0 * 1000 + 40.0 * 10) / 1010, 4)


async def test_a_cluster_no_row_reported_a_position_for_has_none(
    db_session: AsyncSession,
) -> None:
    """None, not 0: the denominator is empty, so there is no average to report."""
    repo = AdvertisingClusterRepository(db_session)
    await repo.upsert_many([_row(nm_id=MINE, cluster="носки", avg_position=0.0)])
    await db_session.flush()

    (aggregate,) = await repo.aggregate_for_sku(
        nm_id=MINE, date_from=WINDOW[0], date_to=WINDOW[1], limit=50
    )

    assert aggregate.avg_position is None


async def test_the_daily_trend_is_scoped_to_the_sku_too(db_session: AsyncSession) -> None:
    """A separate statement, so the per-SKU predicate has to be repeated in it."""
    repo = AdvertisingClusterRepository(db_session)
    await repo.upsert_many(
        [
            _row(nm_id=MINE, cluster="носки", day=DAY_1, views=100),
            _row(nm_id=OTHER_SKU, cluster="носки", day=DAY_1, views=900),
        ]
    )
    await db_session.flush()

    series = await repo.daily_series_for_sku(
        nm_id=MINE, clusters=["носки"], date_from=WINDOW[0], date_to=WINDOW[1]
    )

    assert [(point.stat_date, point.views) for point in series] == [(DAY_1, 100)]


async def test_re_harvesting_a_day_overwrites_the_clusters_values(
    db_session: AsyncSession,
) -> None:
    """The four-column key must make a re-harvest idempotent, not duplicate rows."""
    repo = AdvertisingClusterRepository(db_session)
    await repo.upsert_many([_row(nm_id=MINE, cluster="носки", views=100)])
    await repo.upsert_many([_row(nm_id=MINE, cluster="носки", views=250)])
    await db_session.flush()

    (aggregate,) = await repo.aggregate_for_sku(
        nm_id=MINE, date_from=WINDOW[0], date_to=WINDOW[1], limit=50
    )

    assert aggregate.views == 250


async def test_the_sweep_only_clears_the_named_campaigns_window(
    db_session: AsyncSession,
) -> None:
    """A refresh of one campaign must not erase another campaign's clusters."""
    repo = AdvertisingClusterRepository(db_session)
    await repo.upsert_many(
        [
            _row(nm_id=MINE, cluster="носки", campaign_id=CAMPAIGN),
            _row(nm_id=MINE, cluster="футболка", campaign_id=999),
        ]
    )
    await db_session.flush()

    deleted = await repo.delete_window_for_campaigns(
        date_from=WINDOW[0], date_to=WINDOW[1], campaign_ids=[CAMPAIGN]
    )
    await db_session.flush()

    remaining = await repo.aggregate_for_sku(
        nm_id=MINE, date_from=WINDOW[0], date_to=WINDOW[1], limit=50
    )
    assert deleted == 1
    assert [row.cluster for row in remaining] == ["футболка"]
