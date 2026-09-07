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
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from src.integrations.wildberries.schemas import WBAdvertV2


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


__all__ = ["campaigns_for_sku"]
