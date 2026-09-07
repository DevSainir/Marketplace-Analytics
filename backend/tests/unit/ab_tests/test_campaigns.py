"""Unit tests for campaign discovery (services/campaigns.py).

The defect this exists to prevent has no error in it. If the campaign serving a
card is not in the list, ``fullstats`` answers about the other campaigns quite
happily, the counters come back zero, and every photo is credited with nothing —
a test that ran, finished, and measured a card that was being advertised the
whole time.

Measured on production 2026-09-07: campaign 97455930 served nm 1944299862 259
impressions while the running test sat at zero, because the campaign was newer
than the last nightly harvest and discovery read the harvest.
"""

from __future__ import annotations

import pytest

from src.integrations.wildberries.schemas import WBAdvertV2
from src.modules.ab_tests.services.campaigns import campaigns_for_sku

NM_TROUSERS = 1944299862
NM_OTHER = 995716075


def _advert(campaign_id: int, *nm_ids: int, status: int = 9) -> WBAdvertV2:
    """One campaign descriptor, shaped as WB's v2 listing sends it."""
    return WBAdvertV2.model_validate(
        {
            "id": campaign_id,
            "status": status,
            "bid_type": "unified",
            "nm_settings": [{"nm_id": nm_id} for nm_id in nm_ids],
        }
    )


def test_a_campaign_started_since_the_last_harvest_is_found() -> None:
    """The whole point: a seller starts a campaign, then starts a test on it."""
    adverts = [_advert(97455930, NM_TROUSERS), _advert(97136532, NM_OTHER)]

    assert campaigns_for_sku(adverts, nm_id=NM_TROUSERS, known=[]) == [97455930]


def test_campaigns_that_do_not_name_the_sku_are_left_out() -> None:
    """A pass reads one card; WB caps `ids` at 50 per request."""
    adverts = [_advert(1, NM_OTHER), _advert(2, NM_OTHER, NM_TROUSERS), _advert(3, NM_OTHER)]

    assert campaigns_for_sku(adverts, nm_id=NM_TROUSERS) == [2]


def test_harvested_ids_survive_a_campaign_wb_no_longer_lists() -> None:
    """An archived campaign's counters are still part of what a photo earned."""
    adverts = [_advert(97455930, NM_TROUSERS)]

    assert campaigns_for_sku(adverts, nm_id=NM_TROUSERS, known=[97136532, 97455930]) == [
        97136532,
        97455930,
    ]


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(9, id="идут показы"),
        pytest.param(11, id="на паузе"),
        pytest.param(7, id="завершена"),
        pytest.param(4, id="готова к запуску"),
    ],
)
def test_status_does_not_decide_whether_a_campaign_is_read(status: int) -> None:
    """A campaign switched off mid-test still served the half before it.

    Counters are cumulative and differenced, so a campaign that is no longer
    running can only contribute traffic the card really earned. Filtering on
    status would drop exactly the campaign a seller paused halfway through the
    test they are trying to read.
    """
    adverts = [_advert(97455930, NM_TROUSERS, status=status)]

    assert campaigns_for_sku(adverts, nm_id=NM_TROUSERS) == [97455930]


def test_a_card_with_no_campaigns_reads_nothing_rather_than_everything() -> None:
    """An empty list must not become "ask about every campaign on the account"."""
    adverts = [_advert(1, NM_OTHER)]

    assert campaigns_for_sku(adverts, nm_id=NM_TROUSERS) == []
