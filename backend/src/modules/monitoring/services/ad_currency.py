"""Planning the fullstats calls that name the currency of old advertising rows.

Rows harvested before 2026-09-29 were stored without the campaign's currency,
and nothing but WB can say what it was: RUB for campaigns created before WB
moved the ad account to KGS on 2026-08-20, KGS for later ones, both inside one
кабинет (wildberries-api, ``references/currencies.md``). fullstats states it on
every campaign it answers for, so one call can label up to fifty campaigns —
provided each of them actually delivered inside the call's window, because
fullstats says nothing at all about a campaign that did not.

This module only plans; ``scripts/backfill/ad_currency.py`` makes the calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

#: fullstats caps one request at 31 days.
PROBE_WINDOW_DAYS = 31

#: …and at this many campaign ids (``WBAdvertisingClient._FULLSTATS_BATCH``).
PROBE_BATCH = 50


@dataclass(frozen=True)
class CurrencyProbe:
    """One fullstats call: a window every listed campaign delivered in."""

    begin: date
    end: date
    campaign_ids: list[int]


def plan_currency_probes(
    last_days: dict[int, date],
    *,
    batch: int = PROBE_BATCH,
    window_days: int = PROBE_WINDOW_DAYS,
) -> list[CurrencyProbe]:
    """Group campaigns into as few fullstats calls as their last days allow.

    Each campaign is keyed by its last stored day, which is a day fullstats
    provably answers for it. Walking newest first, a call opens at the newest
    remaining day and takes every campaign whose last day falls within the
    31 days before it, up to the batch size — so an account whose campaigns
    all ran recently costs one call per fifty, and a long tail of old ones
    costs a call per month it spans.

    Args:
        last_days: ``{campaign_id: last stored day}``.
        batch: Most campaign ids per call.
        window_days: Longest window per call.

    Returns:
        The calls, newest window first; each window as narrow as its campaigns.
    """
    ordered = sorted(last_days.items(), key=lambda item: (item[1], item[0]), reverse=True)
    probes: list[CurrencyProbe] = []
    index = 0
    while index < len(ordered):
        end = ordered[index][1]
        floor = end - timedelta(days=window_days - 1)
        ids: list[int] = []
        begin = end
        while index < len(ordered) and len(ids) < batch and ordered[index][1] >= floor:
            campaign_id, day = ordered[index]
            ids.append(campaign_id)
            begin = min(begin, day)
            index += 1
        probes.append(CurrencyProbe(begin=begin, end=end, campaign_ids=sorted(ids)))
    return probes
