"""Unit tests for the per-search-cluster advertising ingestion.

What these pin: the cluster TEXT survives ingestion (the zone aggregate sums it
away, and «Поиск по кластерам» has no other source for it), and the average
position is weighted by impressions instead of averaged flat.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.integrations.wildberries.schemas import (
    WBNormQueryDaily,
    WBNormQueryItem,
    WBNormQueryStat,
)
from src.modules.monitoring.services.ingestion.advertising import AdvertisingIngestion

CAMPAIGN = 63214674
NM_ID = 953770957
DAY = date(2026, 8, 10)


class _CapturingClusterRepo:
    """Stands in for AdvertisingClusterRepository, recording what it is given."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.swept: list[dict[str, Any]] = []

    async def upsert_many(self, rows: list[dict[str, Any]]) -> int:
        self.rows = rows
        return len(rows)

    async def delete_window_for_campaigns(
        self, *, date_from: date, date_to: date, campaign_ids: Any
    ) -> int:
        self.swept.append(
            {"date_from": date_from, "date_to": date_to, "campaign_ids": list(campaign_ids)}
        )
        return 0


def _ingestion(cluster_repo: Any) -> AdvertisingIngestion:
    """Build the unit with only the cluster repo wired (others unused here)."""
    return AdvertisingIngestion(
        advertising_repo=None,  # type: ignore[arg-type]
        campaign_repo=None,  # type: ignore[arg-type]
        advertising_search_repo=None,  # type: ignore[arg-type]
        advertising_cluster_repo=cluster_repo,
    )


def _item(*stats: WBNormQueryStat, day: date = DAY) -> WBNormQueryItem:
    """One normquery item carrying the given cluster stats on one day."""
    return WBNormQueryItem(
        campaign_id=CAMPAIGN,
        nm_id=NM_ID,
        daily_stats=[WBNormQueryDaily(stat_date=day, stat=stat) for stat in stats],
    )


def _stat(
    norm_query: str,
    *,
    views: int = 100,
    clicks: int = 5,
    atbs: int = 2,
    orders: int = 1,
    spend: float = 50.0,
    avg_position: float = 0.0,
) -> WBNormQueryStat:
    """One cluster's day of metrics."""
    return WBNormQueryStat(
        norm_query=norm_query,
        views=views,
        clicks=clicks,
        atbs=atbs,
        orders=orders,
        spend=spend,
        avg_position=avg_position,
    )


async def test_each_cluster_keeps_its_own_row_and_text() -> None:
    """One row per cluster phrase, keyed by it — the aggregate loses the phrase."""
    repo = _CapturingClusterRepo()
    items = [_item(_stat("носки мужские", views=300), _stat("носки короткие", views=120))]

    count = await _ingestion(repo).ingest_search_clusters(items)

    assert count == 2
    assert {(row["cluster"], row["views"]) for row in repo.rows} == {
        ("носки мужские", 300),
        ("носки короткие", 120),
    }


async def test_a_cluster_repeated_within_a_day_is_summed_not_overwritten() -> None:
    """Two entries for one phrase on one day are one row carrying both.

    The four columns are a composite primary key, so a second entry for the same
    key would otherwise silently replace the first and undercount the day.
    """
    repo = _CapturingClusterRepo()
    items = [_item(_stat("носки", views=100, clicks=4), _stat("носки", views=50, clicks=3))]

    await _ingestion(repo).ingest_search_clusters(items)

    assert len(repo.rows) == 1
    assert repo.rows[0]["views"] == 150
    assert repo.rows[0]["clicks"] == 7


async def test_an_entry_without_a_cluster_text_is_dropped() -> None:
    """A blank phrase is not searchable, and the zone aggregate already counts it."""
    repo = _CapturingClusterRepo()
    items = [_item(_stat(""), _stat("   "), _stat("носки"))]

    await _ingestion(repo).ingest_search_clusters(items)

    assert [row["cluster"] for row in repo.rows] == ["носки"]


async def test_average_position_is_weighted_by_impressions() -> None:
    """A day at position 3 with 1000 views outweighs one at 40 with 10.

    A flat mean would report ~21 — a position the ads never held — and would make
    a cheap long-tail cluster look like a ranking problem.
    """
    repo = _CapturingClusterRepo()
    items = [
        _item(_stat("носки", views=1000, avg_position=3.0), day=DAY),
        _item(_stat("носки", views=10, avg_position=40.0), day=DAY),
    ]

    await _ingestion(repo).ingest_search_clusters(items)

    assert repo.rows[0]["avg_position"] == (3.0 * 1000 + 40.0 * 10) / 1010


async def test_impressions_without_a_reported_position_do_not_dilute_the_average() -> None:
    """WB omitting the position means unknown, not "first place".

    Counting those views in the denominator alone would pull every average
    towards zero and quietly invent a top-of-page ranking.
    """
    repo = _CapturingClusterRepo()
    items = [
        _item(_stat("носки", views=100, avg_position=8.0)),
        _item(_stat("носки", views=900, avg_position=0.0)),
    ]

    await _ingestion(repo).ingest_search_clusters(items)

    assert repo.rows[0]["avg_position"] == 8.0


async def test_all_zero_cluster_rows_are_not_persisted() -> None:
    """A phrase that served nothing carries no signal, only noise."""
    repo = _CapturingClusterRepo()
    items = [_item(_stat("носки", views=0, clicks=0, atbs=0, orders=0, spend=0.0))]

    count = await _ingestion(repo).ingest_search_clusters(items)

    assert count == 0
    assert repo.rows == []


async def test_the_window_is_swept_for_every_requested_campaign_before_insert() -> None:
    """A campaign that stopped bidding on a phrase must lose its stale rows.

    Upserts alone can never delete: the dropped cluster simply stops appearing in
    the payload, so without the sweep it would stay in the report forever.
    """
    repo = _CapturingClusterRepo()
    items = [_item(_stat("носки"))]

    await _ingestion(repo).ingest_search_clusters(
        items,
        window=(date(2026, 8, 1), date(2026, 8, 13)),
        requested_campaign_ids=[CAMPAIGN, 999],
    )

    assert repo.swept == [
        {
            "date_from": date(2026, 8, 1),
            "date_to": date(2026, 8, 13),
            "campaign_ids": [CAMPAIGN, 999],
        }
    ]
