"""Unit tests for turning WB's cumulative counters into intervals.

This module replaced a per-day attribution pass, and with it the rule that the
day of a swap belonged to nobody. The premise changed deliberately: WB serves
the CURRENT advertising day and it moves within minutes (verified live on
2026-09-04 — four campaigns gained 75–112 impressions over an eight-minute gap),
so traffic is the difference between two readings and the grain is a poll rather
than a day.

What is pinned here is everything about that subtraction that fails silently:
a reading that goes backwards, a midnight rollover, and the very first reading
of a test, which describes traffic the test never owned.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from src.integrations.wildberries.schemas.advertising import WBAdvCampaignStats
from src.modules.ab_tests.services.collection import (
    Counters,
    counters_by_day,
    counters_from_reading,
    days_to_read,
    window_delta,
)

NM_UNDER_TEST = 995716075
SIBLING_NM = 1948347102

DAY_1 = date(2026, 9, 3)
DAY_2 = date(2026, 9, 4)


def _nm(nm_id: int, **counts: Any) -> dict[str, Any]:
    """One ``nms[]`` row as WB spells it."""
    return {
        "nmId": nm_id,
        "views": counts.get("views", 0),
        "clicks": counts.get("clicks", 0),
        "atbs": counts.get("atbs", 0),
        "orders": counts.get("orders", 0),
        "sum": counts.get("sum", 0.0),
    }


def _campaign(campaign_id: int, days: list[dict[str, Any]]) -> WBAdvCampaignStats:
    """A parsed fullstats campaign node."""
    return WBAdvCampaignStats.model_validate({"advertId": campaign_id, "days": days})


def _day(stat_date: date, nms: list[dict[str, Any]], app_type: int = 1) -> dict[str, Any]:
    """One ``days[]`` node with a single platform bucket."""
    return {"date": stat_date.isoformat(), "apps": [{"appType": app_type, "nms": nms}]}


# --------------------------------------------------------------------------- #
# Reading the payload
# --------------------------------------------------------------------------- #


def test_a_days_reading_sums_platforms_and_campaigns() -> None:
    """One day's counters are the total over every bucket serving this SKU.

    fullstats splits a campaign-day across platforms and across every nm the
    campaign touched; reading a single bucket as "the day" understates every
    metric and would make the rotation advance far too slowly.
    """
    campaigns = [
        _campaign(
            111,
            [
                {
                    "date": DAY_2.isoformat(),
                    "apps": [
                        {
                            "appType": 1,
                            "nms": [_nm(NM_UNDER_TEST, views=1000, clicks=90, sum=1500.0)],
                        },
                        {
                            "appType": 3,
                            "nms": [_nm(NM_UNDER_TEST, views=500, clicks=40, sum=700.0)],
                        },
                    ],
                }
            ],
        ),
        _campaign(222, [_day(DAY_2, [_nm(NM_UNDER_TEST, views=250, clicks=20, sum=300.0)])]),
    ]

    reading = counters_by_day(campaigns, nm_id=NM_UNDER_TEST)

    assert reading[DAY_2].views == 1750
    assert reading[DAY_2].clicks == 150
    assert reading[DAY_2].spend == Decimal("2500.0")


def test_another_skus_rows_are_not_counted() -> None:
    """A sibling size booked inside the same campaign-day contributes nothing.

    WB books the variant the buyer actually converted on as its own ``nms[]``
    row with no views of its own; counting it would hand this test free orders.
    """
    campaigns = [
        _campaign(
            111,
            [
                _day(
                    DAY_2,
                    [
                        _nm(NM_UNDER_TEST, views=1000, clicks=90, atbs=8, orders=3),
                        _nm(SIBLING_NM, views=0, clicks=0, atbs=4, orders=9),
                    ],
                )
            ],
        )
    ]

    reading = counters_by_day(campaigns, nm_id=NM_UNDER_TEST)

    assert (reading[DAY_2].atbs, reading[DAY_2].orders) == (8, 3)


def test_a_sku_absent_from_the_payload_reads_as_no_days() -> None:
    """A card that was not served has no counters, not zeroed ones."""
    campaigns = [_campaign(111, [_day(DAY_2, [_nm(SIBLING_NM, views=900)])])]

    assert counters_by_day(campaigns, nm_id=NM_UNDER_TEST) == {}


# --------------------------------------------------------------------------- #
# The subtraction
# --------------------------------------------------------------------------- #


def test_the_interval_is_the_growth_since_the_previous_reading() -> None:
    """A window carries what arrived between two polls, not the running total.

    This is the whole reason a photo can rotate several times a day: the
    counters are cumulative, and the difference is a five-minute interval.
    """
    previous = {DAY_2: Counters(views=6937, clicks=238, atbs=45, orders=15)}
    current = {DAY_2: Counters(views=7049, clicks=245, atbs=49, orders=16)}

    delta = window_delta(current=current, previous=previous)

    assert (delta.views, delta.clicks, delta.atbs, delta.orders) == (112, 7, 4, 1)


def test_a_reading_that_goes_backwards_yields_zero_not_a_negative() -> None:
    """A restated day never gives a photo back impressions it already earned.

    WB revises recent days downward (a click reclassified, a fraudulent order
    dropped), and a campaign that stops being returned reads as a fall to
    nothing. A negative window would silently rewind the rotation's counter.
    """
    previous = {DAY_2: Counters(views=7049, clicks=245, orders=16)}
    current = {DAY_2: Counters(views=7000, clicks=245, orders=15)}

    delta = window_delta(current=current, previous=previous)

    assert (delta.views, delta.clicks, delta.orders) == (0, 0, 0)


def test_midnight_starts_a_new_day_without_losing_the_old_one() -> None:
    """At a rollover today counts in full and yesterday keeps its corrections.

    The counters restart at Moscow midnight, so today has no snapshot to
    subtract; comparing against yesterday's total instead would clamp the whole
    interval to zero and stall the rotation until the next evening.
    """
    previous = {DAY_1: Counters(views=20_000, clicks=800)}
    current = {DAY_1: Counters(views=20_050, clicks=805), DAY_2: Counters(views=430, clicks=18)}

    delta = window_delta(current=current, previous=previous)

    assert delta.views == 480  # 50 late on yesterday + 430 so far today
    assert delta.clicks == 23


def test_days_to_read_covers_yesterday_as_well_as_today() -> None:
    """One poll asks for both days, so a rollover closes cleanly."""
    assert list(days_to_read(DAY_2)) == [DAY_1, DAY_2]


def test_an_empty_previous_reading_returns_the_whole_current_one() -> None:
    """With no baseline the subtraction is the identity.

    That is exactly why the runner must NOT write a window on a test's first
    poll: the number is real, but it describes traffic from before the test
    started.
    """
    current = {DAY_2: Counters(views=6937, clicks=238)}

    assert window_delta(current=current, previous={}).views == 6937


def test_counters_add_up_across_days() -> None:
    """Counters compose, so folding several days into one window is addition."""
    total = Counters(views=1, clicks=2) + Counters(views=10, clicks=20, spend=Decimal("5"))

    assert (total.views, total.clicks, total.spend) == (11, 22, Decimal("5"))


def test_empty_counters_are_recognisable() -> None:
    """A window with nothing in it is not written at all, so it must be detectable."""
    assert Counters().is_empty is True
    assert Counters(views=1).is_empty is False
    assert Counters(spend=Decimal("0.01")).is_empty is False


def test_a_stored_snapshot_row_reads_back_as_counters() -> None:
    """The repository's rows and the poller's arithmetic speak the same type."""
    restored = counters_from_reading(views=10, clicks=2, atbs=1, orders=0, spend=Decimal("3.50"))

    assert restored == Counters(views=10, clicks=2, atbs=1, orders=0, spend=Decimal("3.50"))
