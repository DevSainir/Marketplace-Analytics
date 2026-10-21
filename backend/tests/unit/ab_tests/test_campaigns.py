"""Unit tests for campaign discovery (services/campaigns.py).

The defect this exists to prevent has no error in it. If the campaign serving a
card is not in the list, ``fullstats`` answers about the other campaigns quite
happily, the counters come back zero, and every photo is credited with nothing —
a test that ran, finished, and measured a card that was being advertised the
whole time.

Seen 2026-09-07: a campaign served the card a few hundred impressions while the
running test sat at zero, because the campaign was newer than the last nightly
harvest and discovery read the harvest.
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


def test_a_harvested_campaign_is_read_while_it_is_still_running() -> None:
    """The harvest can name a campaign this card's settings do not.

    An automatic campaign picks cards up on its own, so ``nm_settings`` need not
    mention the SKU whose traffic it is bringing. Recent traffic is the other
    way of knowing — but only for as long as WB still says the campaign can
    deliver.
    """
    adverts = [_advert(97455930, NM_TROUSERS), _advert(97136532, NM_OTHER)]

    assert campaigns_for_sku(adverts, nm_id=NM_TROUSERS, known=[97136532, 97455930]) == [
        97136532,
        97455930,
    ]


def test_a_harvested_campaign_wb_has_finished_is_not_read_again() -> None:
    """The month-old ids are precisely the campaigns that have since ended.

    What each of them earned is already in the windows it earned it in. Asking
    WB about it again gets a day's cumulative counters with no snapshot to
    difference them against, and the page grows a branch for a campaign that
    served nothing during the test.
    """
    adverts = [_advert(97455930, NM_TROUSERS), _advert(97136532, NM_OTHER, status=7)]

    assert campaigns_for_sku(adverts, nm_id=NM_TROUSERS, known=[97136532]) == [97455930]


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(9, id="идут показы"),
        pytest.param(11, id="на паузе"),
    ],
)
def test_a_campaign_that_can_still_deliver_is_read(status: int) -> None:
    """Active and paused are the two statuses a campaign can still serve from.

    The same pair monitoring's harvest planner keeps. A paused campaign is one
    click from running again, and the seller who paused it mid-test expects the
    half it served to go on being counted.
    """
    adverts = [_advert(97455930, NM_TROUSERS, status=status)]

    assert campaigns_for_sku(adverts, nm_id=NM_TROUSERS) == [97455930]


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(7, id="завершена"),
        pytest.param(4, id="готова к запуску"),
        pytest.param(8, id="отклонена"),
        pytest.param(-1, id="удаляется"),
    ],
)
def test_a_campaign_that_cannot_deliver_is_left_out(status: int) -> None:
    """Every other status is past tense, or has never started.

    A card advertised for a month names a dozen of them, and reading each one
    put a branch of «0 показов» under every figure of «Итог по тесту» — seven
    branches where only two campaigns were running (seen 2026-09-19).
    """
    adverts = [_advert(97455930, NM_TROUSERS, status=status)]

    assert campaigns_for_sku(adverts, nm_id=NM_TROUSERS) == []


def test_a_card_with_no_campaigns_reads_nothing_rather_than_everything() -> None:
    """An empty list must not become "ask about every campaign on the account"."""
    adverts = [_advert(1, NM_OTHER)]

    assert campaigns_for_sku(adverts, nm_id=NM_TROUSERS) == []
