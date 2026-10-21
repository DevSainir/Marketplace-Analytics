"""Turning WB's cumulative advertising counters into per-interval traffic.

``/adv/v3/fullstats`` will not serve an interval shorter than a day, but the day
it serves is the CURRENT one and it moves within minutes — verified live on
2026-09-04, four campaigns gaining 75-112 impressions over an eight-minute gap.
So the counters are cumulative-since-Moscow-midnight, and the traffic of any
interval is the difference between two readings of them.

This module is that subtraction, and the three things that make it safe:

* **Clamped at zero per metric per day.** WB restates recent days downward from
  time to time (a click reclassified, a fraudulent order dropped), and a
  campaign that stops being returned reads as a fall to nothing. A negative
  window would silently give a photo back impressions it had already earned.
* **Split by day.** The counters restart at Moscow midnight, so a reading is
  compared against the snapshot *of the same day*. At a rollover today's
  snapshot is simply absent and today's whole reading is the delta, while
  yesterday keeps accruing its own late corrections.
* **No baseline, no window.** The first reading for a test seeds the snapshot
  and produces nothing. Without that rule a test started at noon would credit
  its first photo with everything the card earned since midnight.

**And it is done per campaign.** A card is often pushed by two campaigns at
once, and the counters used to be added together before they were stored — one
running tally per photo, holding a mixture. That is not a detail of presentation: the
mixture moves on its own. A campaign switched on halfway through a test raises
every photo that follows it, and the rise reads as a photo winning. So the
subtraction happens once per ``(campaign, day)`` pair, and every stored window
names the campaign it came from; the totals are the sum of those, which is the
number the page showed before and still shows.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from src.integrations.wildberries.schemas.advertising import WBAdvCampaignStats


@dataclass(frozen=True)
class Counters:
    """Advertising counts — cumulative in a snapshot, incremental in a window."""

    views: int = 0
    clicks: int = 0
    atbs: int = 0
    orders: int = 0
    spend: Decimal = field(default_factory=lambda: Decimal("0"))

    def __add__(self, other: Counters) -> Counters:
        """Sum two readings (used to fold several days into one window)."""
        return Counters(
            views=self.views + other.views,
            clicks=self.clicks + other.clicks,
            atbs=self.atbs + other.atbs,
            orders=self.orders + other.orders,
            spend=self.spend + other.spend,
        )

    @property
    def is_empty(self) -> bool:
        """True when nothing at all was counted."""
        return not (self.views or self.clicks or self.atbs or self.orders or self.spend)


#: One test's cumulative reading: ``{campaign_id: {day: counters}}``.
CampaignDays = dict[int, dict[date, Counters]]


def counters_by_campaign_day(
    campaigns: Sequence[WBAdvCampaignStats], *, nm_id: int
) -> CampaignDays:
    """Fold a fullstats answer into cumulative counters per campaign per day.

    fullstats splits a campaign-day across platforms (``apps[]``) and across
    every SKU the campaign touched (``nms[]``), including sibling sizes booked
    with ``views = clicks = 0``. One campaign-day's reading for this test is the
    sum over platforms of the rows for *its own* nm — and only the platforms
    are summed away, because the campaign is what the split exists to keep.

    Args:
        campaigns: Parsed ``/adv/v3/fullstats`` campaign nodes.
        nm_id: The SKU under test; every other SKU's rows are ignored.

    Returns:
        ``{campaign_id: {day: cumulative counters}}``. A campaign that never
        served this SKU is absent rather than present with zeroes: the poller
        differences what it finds, and an invented zero baseline would credit a
        whole day's traffic to one window the first time the campaign appeared.
    """
    per_campaign: CampaignDays = {}

    for campaign in campaigns:
        for day in campaign.days:
            for app in day.apps:
                for row in app.nms:
                    if row.nm_id != nm_id:
                        continue
                    days = per_campaign.setdefault(campaign.campaign_id, {})
                    days[day.stat_date] = days.get(day.stat_date, Counters()) + Counters(
                        views=row.views,
                        clicks=row.clicks,
                        atbs=row.atbs,
                        orders=row.orders,
                        spend=Decimal(str(row.sum)),
                    )
    return per_campaign


def counters_by_day(campaigns: Sequence[WBAdvCampaignStats], *, nm_id: int) -> dict[date, Counters]:
    """The same reading with the campaigns added back together.

    Kept for the one caller that genuinely wants the mixture — a total is a
    total whatever paid for it — and implemented as a fold of the split so the
    two can never disagree about it.

    Args:
        campaigns: Parsed ``/adv/v3/fullstats`` campaign nodes.
        nm_id: The SKU under test.

    Returns:
        ``{day: cumulative counters}``, summed over campaigns.
    """
    per_day: dict[date, Counters] = {}
    for days in counters_by_campaign_day(campaigns, nm_id=nm_id).values():
        for day, counters in days.items():
            per_day[day] = per_day.get(day, Counters()) + counters
    return per_day


def counters_from_reading(
    *, views: int, clicks: int, atbs: int, orders: int, spend: Decimal
) -> Counters:
    """Rebuild counters from a stored snapshot row.

    A named constructor rather than a bare call so the repository and the
    arithmetic cannot drift apart on field order.

    Args:
        views: Cumulative impressions.
        clicks: Cumulative clicks.
        atbs: Cumulative add-to-basket events.
        orders: Cumulative orders.
        spend: Cumulative spend.

    Returns:
        The counters.
    """
    return Counters(views=views, clicks=clicks, atbs=atbs, orders=orders, spend=spend)


def _clamped_difference(current: Counters, previous: Counters) -> Counters:
    """One day's gain, never negative in any metric."""
    return Counters(
        views=max(0, current.views - previous.views),
        clicks=max(0, current.clicks - previous.clicks),
        atbs=max(0, current.atbs - previous.atbs),
        orders=max(0, current.orders - previous.orders),
        spend=max(Decimal("0"), current.spend - previous.spend),
    )


def campaign_deltas(*, current: CampaignDays, previous: CampaignDays) -> dict[int, Counters]:
    """Traffic gained per campaign between two readings.

    Every campaign named by either side is answered for. A campaign in
    ``previous`` and gone from ``current`` — WB stopped returning it — reads as
    a fall to nothing and is clamped to zero by :func:`window_delta`, never as
    impressions taken back off the photo that earned them.

    Args:
        current: This poll's cumulative counters, per campaign per day.
        previous: The stored snapshot's, in the same shape.

    Returns:
        ``{campaign_id: interval traffic}``, empty entries included so the
        caller decides what an all-zero campaign means.
    """
    return {
        campaign_id: window_delta(
            current=current.get(campaign_id, {}), previous=previous.get(campaign_id, {})
        )
        for campaign_id in sorted({*current, *previous})
    }


def window_delta(*, current: dict[date, Counters], previous: dict[date, Counters]) -> Counters:
    """Traffic gained between two readings, summed over the days they span.

    Args:
        current: This poll's cumulative counters, by day.
        previous: The stored snapshot's counters, by the same days.

    Returns:
        The interval's traffic. A day absent from ``previous`` contributes its
        whole current reading, which is what a midnight rollover looks like.
    """
    total = Counters()
    for day, reading in current.items():
        total = total + _clamped_difference(reading, previous.get(day, Counters()))
    return total


def days_to_read(today: date, *, lookback_days: int = 1) -> Iterable[date]:
    """Which advertising days one poll should ask for.

    Yesterday is included alongside today so a poll that lands just after
    midnight still closes out the previous day, and so WB's late restatements of
    a day already closed are picked up rather than frozen at the last reading
    before the rollover.

    Args:
        today: Today in Moscow time.
        lookback_days: How many days before today to re-read.

    Returns:
        The days, oldest first.
    """
    return [today - timedelta(days=offset) for offset in range(lookback_days, -1, -1)]
