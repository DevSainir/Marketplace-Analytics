"""Unit tests for campaign settings — the retired single-zone types WB no longer describes.

``adverts-v2`` answers only for the campaign types alive since 2024. The
retired ones still come back from ``promotion/count`` and still carry spend in
``fullstats``, so without a bid type and placements both the matrix and
"Advertising" leave their money unclassified (for example, type-6 campaigns
from 2023).
"""

from __future__ import annotations

from typing import Any

from src.integrations.wildberries.schemas import WBCampaign
from src.modules.monitoring.services import IngestionService


class _CapturingCampaignRepo:
    """Stands in for CampaignRepository."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.with_settings: bool | None = None

    async def upsert_many(self, rows: list[dict[str, Any]], *, with_settings: bool = False) -> int:
        self.rows = rows
        self.with_settings = with_settings
        return len(rows)


def _service(campaign_repo: Any) -> IngestionService:
    """Build an IngestionService with only the campaign repo wired."""
    return IngestionService(
        funnel_repo=None,  # type: ignore[arg-type]
        advertising_repo=None,  # type: ignore[arg-type]
        stock_repo=None,  # type: ignore[arg-type]
        campaign_repo=campaign_repo,
        product_card_repo=None,  # type: ignore[arg-type]
        product_size_repo=None,  # type: ignore[arg-type]
        advertising_search_repo=None,  # type: ignore[arg-type]
        advertising_cluster_repo=None,  # type: ignore[arg-type]
        advertising_write_off_repo=None,  # type: ignore[arg-type]
        price_repo=None,  # type: ignore[arg-type]
        sale_repo=None,  # type: ignore[arg-type]
    )


async def _ingest(*campaigns: WBCampaign) -> dict[int, dict[str, Any]]:
    repo = _CapturingCampaignRepo()
    await _service(repo).ingest_campaigns(list(campaigns), adverts=[])
    return {row["campaign_id"]: row for row in repo.rows}


async def test_a_retired_search_campaign_is_manual_cpm_in_search() -> None:
    rows = await _ingest(WBCampaign(campaign_id=52367544, type=6, status=7))

    row = rows[52367544]
    assert (row["bid_type"], row["payment_type"]) == ("manual", "cpm")
    assert (row["placement_search"], row["placement_recommendations"]) == (True, False)


async def test_retired_card_and_home_campaigns_are_manual_cpm_on_the_shelves() -> None:
    rows = await _ingest(
        WBCampaign(campaign_id=1, type=5, status=7),
        WBCampaign(campaign_id=2, type=7, status=7),
    )

    for row in rows.values():
        assert row["bid_type"] == "manual"
        assert row["placement_search"] is False
        assert row["placement_recommendations"] is True


async def test_a_live_type_wb_does_not_describe_stays_unknown() -> None:
    # A unified/auction campaign whose settings are missing this run is a sync
    # gap, not a retired type: guessing its zones would misfile real money.
    rows = await _ingest(WBCampaign(campaign_id=3, type=9, status=9))

    assert rows[3]["bid_type"] is None
    assert rows[3]["placement_search"] is None
