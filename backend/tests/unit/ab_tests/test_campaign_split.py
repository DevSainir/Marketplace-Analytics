"""Unit tests for reading one test through one advertising campaign.

Two campaigns on one card used to be added together before anything was
stored, and the whole point of the split is what that concealed: a campaign
switched on — or off — in the middle of a test moves every photo that follows
it, and the move reads exactly like a photo winning.

So the cases here are the three the page has to survive (see
``services/split.py``): one campaign and nothing looks different; a second one
appears mid-test; one of two stops and its half of the history stays put.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from src.integrations.wildberries.schemas import WBAdvCampaignStats, WBAdvertV2
from src.modules.ab_tests.models import (
    AbTestCampaign,
    AbTestVariant,
    VariantExposure,
    VariantStatWindow,
)
from src.modules.ab_tests.services.campaigns import CampaignKind, classify
from src.modules.ab_tests.services.collection import (
    Counters,
    campaign_deltas,
    counters_by_campaign_day,
    counters_by_day,
)
from src.modules.ab_tests.services.split import (
    campaign_totals,
    campaigns_with_traffic,
    variant_campaign_metrics,
)

NM = 1944299862
DAY = date(2026, 9, 8)
T0 = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
UNI, CPC = 97455930, 97730900


def _variant(position: int) -> AbTestVariant:
    """One photo of the rotation."""
    return AbTestVariant(
        id=uuid.uuid4(),
        position=position,
        image_path=f"v/{position}.jpg",
        image_sha256="0" * 64,
        content_type="image/jpeg",
        original_filename=f"{position}.jpg",
    )


def _exposure(variant: AbTestVariant, *, lap: int, start: int, end: int | None) -> VariantExposure:
    """One turn, positioned in minutes from ``T0``."""
    return VariantExposure(
        test_id=uuid.uuid4(),
        variant_id=variant.id,
        round_number=lap,
        activated_at=T0 + timedelta(minutes=start),
        deactivated_at=None if end is None else T0 + timedelta(minutes=end),
    )


def _window(
    variant: AbTestVariant, *, campaign_id: int, at: int, views: int, clicks: int
) -> VariantStatWindow:
    """One measured interval of one campaign, closing ``at`` minutes after ``T0``."""
    return VariantStatWindow(
        test_id=uuid.uuid4(),
        variant_id=variant.id,
        campaign_id=campaign_id,
        window_start=T0 + timedelta(minutes=at - 5),
        window_end=T0 + timedelta(minutes=at),
        views=views,
        clicks=clicks,
        atbs=0,
        orders=0,
        spend=Decimal("0"),
    )


def _fullstats(*rows: tuple[int, int, int]) -> list[WBAdvCampaignStats]:
    """A fullstats answer: ``(campaign_id, views, clicks)`` per campaign."""
    return [
        WBAdvCampaignStats.model_validate(
            {
                "advertId": campaign_id,
                "days": [
                    {
                        "date": DAY.isoformat(),
                        "apps": [{"appType": 1, "nms": [{"nmId": NM, "views": v, "clicks": c}]}],
                    }
                ],
            }
        )
        for campaign_id, v, c in rows
    ]


def _registered(campaign_id: int, *, name: str, kind: CampaignKind) -> AbTestCampaign:
    """A register row, as a pass would have written it."""
    return AbTestCampaign(
        test_id=uuid.uuid4(),
        campaign_id=campaign_id,
        name=name,
        kind=str(kind),
        first_seen_at=T0,
        last_seen_at=T0,
    )


def test_two_campaigns_on_one_card_are_read_apart_and_still_sum_to_the_total() -> None:
    """The split has to be exact, or the headline stops matching its branches."""
    stats = _fullstats((UNI, 6000, 120), (CPC, 2000, 90))

    per_campaign = counters_by_campaign_day(stats, nm_id=NM)
    together = counters_by_day(stats, nm_id=NM)

    assert per_campaign[UNI][DAY].views == 6000
    assert per_campaign[CPC][DAY].views == 2000
    assert together[DAY].views == 8000
    assert together[DAY].clicks == 210


def test_a_campaign_that_starts_mid_test_credits_only_what_it_gained() -> None:
    """The failure the split exists for.

    A second campaign appears between two polls. Its counters are cumulative
    since midnight, so read as one number the card's traffic jumps — and the
    jump lands on whichever photo happens to be standing. Differenced against
    its own absent baseline, it contributes its whole first reading and the
    first campaign contributes only its own growth.
    """
    previous = {UNI: {DAY: Counters(views=6000, clicks=120)}}
    current = {UNI: {DAY: Counters(views=6100, clicks=124)}, CPC: {DAY: Counters(views=300)}}

    deltas = campaign_deltas(current=current, previous=previous)

    assert deltas[UNI].views == 100
    assert deltas[CPC].views == 300


def test_a_campaign_wb_stops_returning_never_takes_impressions_back() -> None:
    """A fall to nothing is a campaign that ended, not negative traffic."""
    deltas = campaign_deltas(
        current={UNI: {DAY: Counters(views=6100)}},
        previous={UNI: {DAY: Counters(views=6000)}, CPC: {DAY: Counters(views=300)}},
    )

    assert deltas[UNI].views == 100
    assert deltas[CPC].views == 0


def test_a_campaign_with_no_traffic_is_not_a_column() -> None:
    """A card can name a campaign that never served it; a branch of zeroes is not a finding."""
    first = _variant(1)
    windows = [_window(first, campaign_id=UNI, at=5, views=100, clicks=4)]

    refs = campaigns_with_traffic(
        windows=windows,
        registered=[
            _registered(UNI, name="Unified, dresses", kind=CampaignKind.UNI),
            _registered(CPC, name="CPC test", kind=CampaignKind.CPC),
        ],
    )

    assert [ref.campaign_id for ref in refs] == [UNI]


def test_a_campaign_that_showed_the_card_to_nobody_is_not_a_column() -> None:
    """Spend with no impressions and no clicks measures nothing the page compares.

    A campaign WB has since finished can still turn up in a fullstats answer
    with a rouble against it and no traffic. Its column is dashes, and seven of
    those under every figure of "Test summary" is what the split was supposed
    to make readable (seen 2026-09-19).
    """
    first = _variant(1)
    billed = _window(first, campaign_id=CPC, at=5, views=0, clicks=0)
    billed.spend = Decimal("1")
    windows = [_window(first, campaign_id=UNI, at=5, views=100, clicks=4), billed]

    refs = campaigns_with_traffic(
        windows=windows,
        registered=[
            _registered(UNI, name="Unified, dresses", kind=CampaignKind.UNI),
            _registered(CPC, name="CPC test", kind=CampaignKind.CPC),
        ],
    )

    assert [ref.campaign_id for ref in refs] == [UNI]


def test_the_campaigns_are_ordered_unified_first_and_cpc_last() -> None:
    """The order the seller reads on every other screen, whichever pair is running."""
    first = _variant(1)
    windows = [
        _window(first, campaign_id=CPC, at=5, views=100, clicks=4),
        _window(first, campaign_id=UNI, at=10, views=100, clicks=4),
    ]

    refs = campaigns_with_traffic(
        windows=windows,
        registered=[
            _registered(CPC, name="CPC", kind=CampaignKind.CPC),
            _registered(UNI, name="Unified", kind=CampaignKind.UNI),
        ],
    )

    assert [ref.kind for ref in refs] == [str(CampaignKind.UNI), str(CampaignKind.CPC)]


def test_the_branches_add_up_to_the_figure_above_them() -> None:
    """The "Test summary" keeps its meaning: the trunk is the sum of the branches."""
    first, second = _variant(1), _variant(2)
    windows = [
        _window(first, campaign_id=UNI, at=5, views=4000, clicks=80),
        _window(second, campaign_id=UNI, at=10, views=2000, clicks=60),
        _window(first, campaign_id=CPC, at=5, views=1000, clicks=50),
    ]
    refs = campaigns_with_traffic(
        windows=windows,
        registered=[
            _registered(UNI, name="Unified", kind=CampaignKind.UNI),
            _registered(CPC, name="CPC", kind=CampaignKind.CPC),
        ],
    )

    totals = campaign_totals(windows=windows, refs=refs)

    assert [row.views for row in totals] == [6000, 1000]
    assert sum(row.views for row in totals) == 7000
    assert sum(row.clicks for row in totals) == 190


def test_a_photo_can_lead_one_campaign_and_trail_the_other() -> None:
    """Why the gap is recomputed inside the campaign rather than carried over."""
    first, second = _variant(1), _variant(2)
    windows = [
        # Unified: photo 1 converts twice as well as photo 2.
        _window(first, campaign_id=UNI, at=5, views=1000, clicks=40),
        _window(second, campaign_id=UNI, at=10, views=1000, clicks=20),
        # CPC: the other way round.
        _window(first, campaign_id=CPC, at=5, views=1000, clicks=10),
        _window(second, campaign_id=CPC, at=10, views=1000, clicks=30),
    ]
    refs = campaigns_with_traffic(
        windows=windows,
        registered=[
            _registered(UNI, name="Unified", kind=CampaignKind.UNI),
            _registered(CPC, name="CPC", kind=CampaignKind.CPC),
        ],
    )

    rows = variant_campaign_metrics(
        variants=[first, second],
        windows=windows,
        exposures=[
            _exposure(first, lap=1, start=0, end=5),
            _exposure(second, lap=1, start=5, end=10),
        ],
        refs=refs,
    )

    uni_first, cpc_first = rows[first.id]
    uni_second, cpc_second = rows[second.id]
    assert uni_first.ctr_result == Decimal("0.00")
    assert uni_second.ctr_result == Decimal("-50.00")
    assert cpc_first.ctr_result == Decimal("-66.67")
    assert cpc_second.ctr_result == Decimal("0.00")


def test_a_campaign_switched_off_mid_test_keeps_the_laps_it_played_and_no_more() -> None:
    """The third case: two campaigns, one stops, the history stays honest.

    The test runs four laps; CPC serves the first two and is switched off. Its
    column has to say «two laps», not «four with two empty» — an empty lap
    reads as a photo that got nothing rather than a campaign that was not
    there.
    """
    first = _variant(1)
    exposures = [
        _exposure(first, lap=lap, start=lap * 10, end=lap * 10 + 5) for lap in (1, 2, 3, 4)
    ]
    windows = [
        _window(first, campaign_id=UNI, at=lap * 10 + 5, views=500, clicks=10)
        for lap in (1, 2, 3, 4)
    ] + [_window(first, campaign_id=CPC, at=lap * 10 + 5, views=200, clicks=8) for lap in (1, 2)]
    refs = campaigns_with_traffic(
        windows=windows,
        registered=[
            _registered(UNI, name="Unified", kind=CampaignKind.UNI),
            _registered(CPC, name="CPC", kind=CampaignKind.CPC),
        ],
    )

    uni, cpc = variant_campaign_metrics(
        variants=[first], windows=windows, exposures=exposures, refs=refs
    )[first.id]

    assert uni.rounds_played == 4
    assert cpc.rounds_played == 2
    assert cpc.views == 400


def test_the_legacy_rows_are_one_unnamed_campaign_rather_than_a_pretence() -> None:
    """Windows written before the split are a mixture and are shown as one thing."""
    first = _variant(1)

    refs = campaigns_with_traffic(
        windows=[_window(first, campaign_id=0, at=5, views=100, clicks=4)], registered=[]
    )

    assert [(ref.campaign_id, ref.kind) for ref in refs] == [(0, str(CampaignKind.UNKNOWN))]
    assert refs[0].name == "Advertising"


def test_a_pay_per_click_campaign_is_cpc_whatever_its_bid_type_says() -> None:
    """WB bills it per click, so it shares no metric with a CPM campaign."""
    advert = WBAdvertV2.model_validate(
        {
            "id": CPC,
            "bid_type": "unified",
            "status": 9,
            "settings": {
                "name": "Dresses CPC",
                "payment_type": "cpc",
                "placements": {"search": True, "recommendations": True},
            },
            "nm_settings": [{"nm_id": NM}],
        }
    )

    assert classify(advert) is CampaignKind.CPC


def test_a_manual_campaign_is_named_by_the_zone_it_runs_in() -> None:
    """A "Manual shelves" campaign is a shelves-only one; search wins a dual one."""

    def advert(search: bool, shelves: bool) -> WBAdvertV2:
        return WBAdvertV2.model_validate(
            {
                "id": UNI,
                "bid_type": "manual",
                "status": 9,
                "settings": {
                    "name": "Manual",
                    "payment_type": "cpm",
                    "placements": {"search": search, "recommendations": shelves},
                },
                "nm_settings": [{"nm_id": NM}],
            }
        )

    assert classify(advert(False, True)) is CampaignKind.MANUAL_SHELVES
    assert classify(advert(True, False)) is CampaignKind.MANUAL_SEARCH
    assert classify(advert(True, True)) is CampaignKind.MANUAL_SEARCH
