"""Pure planning helpers: which campaigns and search pairs a harvest should pull."""

from __future__ import annotations

from collections.abc import Iterable

from src.integrations.wildberries.schemas import WBAdvertV2, WBCampaign

#: WB campaign statuses that are still RUNNING, so they can gain data for a day
#: the harvest has not seen yet: active (9) and paused (11). A campaign leaves
#: this set the moment the seller completes it — including on the day it last
#: delivered, which is why the status alone cannot decide what to pull (see
#: :func:`_advertising_harvest_ids`).
_HARVESTABLE_STATUSES: frozenset[int] = frozenset({9, 11})


def _advertising_harvest_ids(
    campaigns: list[WBCampaign],
    adverts: list[WBAdvertV2] | None,
    nm_ids: list[int],
    recent_campaign_ids: Iterable[int] = (),
) -> list[int]:
    """Pick the campaigns to pull fullstats for, scoped to the harvested SKUs.

    Two sets are pulled, and the union is what the harvest asks WB for.

    * **Still running** — active/paused campaigns, which can gain data for a
      day not yet harvested. When the adverts-v2 settings are available, these
      are further restricted to campaigns whose ``nm_settings`` include one of
      ``nm_ids``, so a single-SKU refresh pulls only that SKU's campaigns
      instead of the whole account's. A full harvest (``nm_ids`` spanning the
      catalogue) keeps essentially every campaign, so the nightly run is
      unaffected. Falls back to all active/paused campaigns when the settings
      source failed.
    * **Recently delivering** — campaigns already holding rows inside the
      harvest window, whatever WB now calls them. Status is a statement about
      *now*, not about the window, so it cannot be trusted to decide which
      days are already complete.

    Args:
        campaigns: Campaign descriptors from ``promotion/count``.
        adverts: Campaign settings from ``adverts-v2`` (``None`` if it failed).
        nm_ids: The SKUs being harvested.
        recent_campaign_ids: Campaigns with persisted rows inside the harvest
            window for ``nm_ids`` — already scoped to those SKUs by the query
            that produced them, so they bypass the ``nm_settings`` filter.

    Returns:
        The campaign ids to request fullstats for.
    """
    active = [c.campaign_id for c in campaigns if c.status in _HARVESTABLE_STATUSES]
    if adverts is None:
        scoped = active
    else:
        wanted = set(nm_ids)
        campaigns_for_sku = {
            advert.campaign_id
            for advert in adverts
            if any(setting.nm_id in wanted for setting in advert.nm_settings)
        }
        scoped = [cid for cid in active if cid in campaigns_for_sku]
    # A campaign that already delivered inside this window is pulled again even
    # once WB stops calling it active, because the day it ENDS on is a day only
    # this pass can still collect: the seller completes the campaign, WB moves
    # it to status 7, and the next harvest would drop it while its final
    # (partial) day was never fetched. Observed 2026-08-20 on an A/B
    # rotation — four campaigns finished mid-day and took part of that day's
    # spend across two SKUs with them, permanently. Re-asking also lets
    # WB's own retroactive corrections to closed campaigns land.
    already_seen = set(scoped)
    return [*scoped, *sorted(cid for cid in recent_campaign_ids if cid not in already_seen)]


def _candidate_search_pairs(
    adverts: list[WBAdvertV2] | None,
    nm_ids: list[int],
    harvest_ids: list[int],
) -> list[tuple[int, int]]:
    """Candidate ``(campaign_id, nm_id)`` pairs for the search-zone slice.

    Every campaign with the SEARCH placement needs the normquery slice:

    * dual-zone campaigns (every unified-bid one, plus dual-placement manual
      ones) — the slice splits «Поиск» from «Полки»;
    * search-only manual campaigns — WB's search campaigns also deliver in
      the CATALOG zone (verified against WB's data: fullstats runs ~10-13% above the
      normquery sum day after day), so the slice splits «Поиск» from
      «Каталог».

    A shelves-only campaign's fullstats already belong wholly to its one zone.
    Pairs are the search-placement campaigns among the scoped harvest set,
    crossed with the harvested SKUs they advertise (from ``nm_settings``).

    Deriving these from campaign SETTINGS (not fullstats results) is what lets
    the normquery call run **concurrently** with fullstats instead of waiting on
    it — the two are the harvest's slowest, formerly-sequential WB round-trips.
    Pairs that turn out not to have delivered simply return empty stats and are
    dropped on ingest, so the persisted result is unchanged.

    Args:
        adverts: Campaign settings from adverts-v2; ``None`` when that source
            failed — no placement flags means no split is possible.
        nm_ids: The SKUs being harvested.
        harvest_ids: The scoped advertising campaign ids (see
            :func:`_advertising_harvest_ids`).

    Returns:
        Sorted, de-duplicated ``(campaign_id, nm_id)`` pairs.
    """
    if adverts is None:
        return []
    wanted = set(nm_ids)
    scoped = set(harvest_ids)
    pairs: set[tuple[int, int]] = set()
    for advert in adverts:
        placements = advert.settings.placements
        if advert.campaign_id not in scoped or not placements.search:
            continue
        for setting in advert.nm_settings:
            if setting.nm_id in wanted:
                pairs.add((advert.campaign_id, setting.nm_id))
    return sorted(pairs)
