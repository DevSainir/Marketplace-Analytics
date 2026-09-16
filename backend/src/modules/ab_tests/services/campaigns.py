"""Which advertising campaigns a test's counters have to be read from.

``fullstats`` is addressed by campaign id, never by SKU, so reading one card's
traffic means first naming every campaign that might be serving it. Where that
list comes from decides whether a test measures anything at all.

**The harvested list is not enough, and the failure is silent.** Monitoring's
``load_campaign_ids_for_workspace`` derives the ids from
``advertising_stat_daily`` — campaigns that have already served *and* been
picked up by the nightly harvest. A campaign started this morning is in neither,
so the poller never asks WB about it, reads zeros, and credits every photo with
nothing. Measured on production 2026-09-07: a live test on nm 1944299862 sat at
zero for half an hour while campaign 97455930 (status 9, «идут показы») served
it 259 impressions, 6 clicks and 64 ₽ — because that campaign had never appeared
in a harvest.

That is not an edge case, it is the common one. A seller starting an A/Б test
starts a campaign for it; the whole point is to measure a card that is being
pushed right now. A discovery path that cannot see a campaign for up to a day
guarantees the two-hour tests are the ones it fails.

So the campaigns are read live, from WB's own ``/api/advert/v2/adverts``, which
carries each campaign's ``nm_settings`` and therefore says directly which ones
name this SKU. The harvested ids are kept alongside them: a campaign that served
last week and has since been archived may be absent from the listing while its
counters are still part of what a variant earned.

**What sort of campaign it is** is decided here too, because the same listing
carries it and because the answer is the order the page shows them in. Two
campaigns on one card are not two of the same thing — «Единая» buys a mixed
placement at a CPM, «CPC» buys clicks — so a photo's CTR under one is not
comparable with its CTR under the other, and that is the whole reason the
counters are now kept apart. The four kinds and their order match the
monitoring matrix's, which the same seller reads on the same day.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Sequence

from src.integrations.wildberries.schemas import WBAdvertV2


class CampaignKind(enum.StrEnum):
    """What sort of advertising a campaign is, in the page's own order.

    ``UNKNOWN`` is not a fifth kind of campaign — it is the absence of an
    answer: a campaign WB no longer lists (archived mid-test), or the legacy
    ``campaign_id = 0`` row that predates the split. It sorts last and is
    labelled without a promise.
    """

    UNI = "uni"
    MANUAL_SEARCH = "manual_search"
    MANUAL_SHELVES = "manual_shelves"
    CPC = "cpc"
    UNKNOWN = "unknown"


#: The order the picker and the summary branches lay campaigns out in — left to
#: right, and stable whichever pair of them a card happens to be running.
KIND_ORDER: dict[str, int] = {
    CampaignKind.UNI: 0,
    CampaignKind.MANUAL_SEARCH: 1,
    CampaignKind.MANUAL_SHELVES: 2,
    CampaignKind.CPC: 3,
    CampaignKind.UNKNOWN: 4,
}

#: What each kind is called on screen.
KIND_LABELS: dict[str, str] = {
    CampaignKind.UNI: "Единая",
    CampaignKind.MANUAL_SEARCH: "Руч. поиск",
    CampaignKind.MANUAL_SHELVES: "Руч. полки",
    CampaignKind.CPC: "CPC",
    CampaignKind.UNKNOWN: "Реклама",
}

#: WB's own word for a pay-per-click campaign, in ``settings.payment_type``.
_CPC_PAYMENT: str = "cpc"

#: WB's word for единая ставка, in ``bid_type``.
_UNIFIED_BID: str = "unified"


def classify(advert: WBAdvertV2) -> CampaignKind:
    """Decide which of the four kinds a campaign is.

    The payment model outranks the bid model, the way the monitoring matrix
    classifies the same campaigns: WB bills a CPC campaign per click rather
    than per 1000 показов, so its CTR, its ставки and its расход share nothing
    with a CPM campaign's whatever its placements say.

    A manual campaign running in BOTH zones is «Руч. поиск»: search is the zone
    it is bought for, and the alternative — a fifth column for something WB's
    own cabinet calls one campaign — would break the order the seller is used
    to for a case that is rare.

    Args:
        advert: One campaign from WB's v2 listing.

    Returns:
        The kind. ``UNKNOWN`` only for a campaign whose listing names neither a
        bid type nor a placement — in practice one being deleted.
    """
    if advert.settings.payment_type.strip().lower() == _CPC_PAYMENT:
        return CampaignKind.CPC
    if advert.bid_type.strip().lower() == _UNIFIED_BID:
        return CampaignKind.UNI
    placements = advert.settings.placements
    if placements.search:
        return CampaignKind.MANUAL_SEARCH
    if placements.recommendations:
        return CampaignKind.MANUAL_SHELVES
    # A manual campaign that names no zone at all. It is not «полки», and
    # saying so would be an invention rather than a default.
    return CampaignKind.UNKNOWN


def sort_key(kind: str, campaign_id: int) -> tuple[int, int]:
    """Order campaigns for display: by kind first, then by id.

    Args:
        kind: The stored kind string.
        campaign_id: WB campaign id, which breaks a tie between two campaigns
            of the same kind — arbitrary, but the same on every render.

    Returns:
        A sort key.
    """
    return (KIND_ORDER.get(kind, KIND_ORDER[CampaignKind.UNKNOWN]), campaign_id)


def display_name(*, name: str, kind: str, campaign_id: int) -> str:
    """What the picker calls one campaign.

    Args:
        name: The campaign's own name in the WB cabinet, possibly empty.
        kind: Its stored kind.
        campaign_id: WB campaign id, the fallback when it has no name.

    Returns:
        The seller's own name where WB gave one, and the kind's label with the
        id otherwise — never a bare id, which names nothing to a reader.
    """
    label = KIND_LABELS.get(kind, KIND_LABELS[CampaignKind.UNKNOWN])
    if name.strip():
        return name.strip()
    return label if not campaign_id else f"{label} {campaign_id}"


def campaigns_for_sku(
    adverts: Iterable[WBAdvertV2], *, nm_id: int, known: Sequence[int] = ()
) -> list[int]:
    """Return every campaign id whose counters may carry this SKU's traffic.

    Statuses are deliberately not filtered. A campaign paused or finished
    mid-test still served part of it, and the counters are read cumulatively and
    differenced — so including one that is no longer running costs a slot in the
    request and can only ever add traffic the card really earned. Filtering to
    «идут показы» would drop exactly the campaign a seller switched off halfway
    through the test they are trying to read.

    Args:
        adverts: WB's campaign listing, each carrying its per-SKU settings.
        nm_id: The card under test.
        known: Ids already discovered from harvested traffic, kept so an
            archived campaign's history is not lost when WB stops listing it.

    Returns:
        Campaign ids, ascending and without duplicates.
    """
    live = {
        advert.campaign_id
        for advert in adverts
        if any(setting.nm_id == nm_id for setting in advert.nm_settings)
    }
    return sorted(live | {int(campaign_id) for campaign_id in known})


__all__ = [
    "KIND_LABELS",
    "KIND_ORDER",
    "CampaignKind",
    "campaigns_for_sku",
    "classify",
    "display_name",
    "sort_key",
]
