"""Which display zone a campaign-day's spend went to — the «На что ушли» buckets.

The rules are the monitoring matrix's (``monitoring/services/matrix/
classification.py``, ``_classify``), restated for money alone: the matrix splits
views, clicks and conversions too, and carries the associated-variant
apportioning with it, none of which a spend table needs. Keep the two in step —
a campaign must land in the same zone on both pages.

* The search slice is WB's ``normquery`` spend; the rest of the campaign-day is
  whatever the campaign's other placement is.
* CPC is its own group whatever the bid type says: paid per click, its money is
  not comparable with a CPM campaign's.
* A manual search-only campaign also delivers in the CATALOG (fullstats runs
  ~10-13 % above the normquery sum), so its remainder is «Каталог». Without a
  harvested slice the whole day stays in «Поиск» — sending ~90 % of a search
  campaign to the catalogue on a missing row would be worse.
* A unified campaign's remainder is «Полки». WB reports no zone finer than the
  search slice for единая ставка, so it has no «Каталог» on this page or on
  the monitoring matrix; in practice it runs almost entirely on the shelves.
"""

from __future__ import annotations

from decimal import Decimal

from src.modules.advertising.schemas import Zone
from src.modules.monitoring.contract import AdCampaignMeta

_ZERO = Decimal(0)


def zone_legs(
    meta: AdCampaignMeta | None, spend: Decimal, search: Decimal | None
) -> list[tuple[Zone, Decimal]]:
    """Split one campaign-day's spend into ``(zone, spend)`` legs that sum to it.

    Args:
        meta: The campaign's settings; ``None`` or no bid type when never synced.
        spend: The campaign-day's ``fullstats`` spend on the кабинет's cards.
        search: Its normquery search-zone spend, ``None`` when none was harvested.
    """
    if meta is None or not meta.bid_type:
        return [("unclassified", spend)]
    in_search = bool(meta.placement_search)
    in_shelves = bool(meta.placement_recommendations)
    # Clamped: the two feeds are harvested at different times, and a search
    # slice a kopeck above the total must not print a negative remainder.
    taken = min(search or _ZERO, spend)
    rest = spend - taken

    if meta.payment_type == "cpc":
        if in_search and in_shelves:
            return [("cpc_search", taken), ("cpc_shelves", rest)]
        return [("cpc_shelves" if in_shelves else "cpc_search", spend)]
    if meta.bid_type == "unified":
        if in_search and in_shelves:
            return [("cpm_unified_search", taken), ("cpm_unified_shelves", rest)]
        return [("cpm_unified_search" if in_search else "cpm_unified_shelves", spend)]
    if in_search and in_shelves:
        return [("cpm_manual_search", taken), ("cpm_manual_shelves", rest)]
    if in_search:
        if search is None:
            return [("cpm_manual_search", spend)]
        return [("cpm_manual_search", taken), ("cpm_manual_catalog", rest)]
    if in_shelves:
        return [("cpm_manual_shelves", spend)]
    return [("unclassified", spend)]
