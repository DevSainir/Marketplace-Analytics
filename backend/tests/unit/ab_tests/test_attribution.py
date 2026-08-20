"""Unit tests for advertising-day attribution (ab_tests/services/attribution.py).

Two things are pinned here, and both are places where a wrong answer looks
right:

* **Which variant owns a day.** WB reports advertising per calendar day and
  nothing finer, so the day a photo is swapped was served under two photos. It
  is attributed to neither — crediting it to either one silently mixes the
  variants it was meant to separate.
* **What a day's numbers are.** ``/adv/v3/fullstats`` splits a campaign-day
  across every platform and every nm it touched, including sibling variants
  booked with ``views = clicks = 0``. A variant's day is the sum over platforms
  and campaigns for *its own* nm — see the advertising reference in the
  ``wildberries-api`` skill.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from src.core.timeutils import MOSCOW_TZ
from src.integrations.wildberries.schemas.advertising import WBAdvCampaignStats
from src.modules.ab_tests.services.attribution import (
    ExposureWindow,
    attribute,
    owner_of_day,
)

NM_UNDER_TEST = 995716075
SIBLING_NM = 1948347102

VARIANT_A = uuid.UUID("00000000-0000-7000-8000-00000000000a")
VARIANT_B = uuid.UUID("00000000-0000-7000-8000-00000000000b")


def _msk(year: int, month: int, day: int, hour: int = 0) -> datetime:
    """A Moscow-time instant — WB's advertising day boundary."""
    return datetime(year, month, day, hour, tzinfo=MOSCOW_TZ)


def _fullstats_day(stat_date: str, nms: list[dict[str, Any]]) -> dict[str, Any]:
    """One ``days[]`` node with a single platform bucket."""
    return {"date": stat_date, "apps": [{"appType": 1, "nms": nms}]}


def _nm(nm_id: int, **counts: Any) -> dict[str, Any]:
    """One ``nms[]`` row as WB spells it."""
    return {
        "nmId": nm_id,
        "views": counts.get("views", 0),
        "clicks": counts.get("clicks", 0),
        "atbs": counts.get("atbs", 0),
        "orders": counts.get("orders", 0),
        "sum": counts.get("sum", 0.0),
        "sum_price": counts.get("sum_price", 0.0),
    }


def _campaign(campaign_id: int, days: list[dict[str, Any]]) -> WBAdvCampaignStats:
    """A parsed fullstats campaign node."""
    return WBAdvCampaignStats.model_validate({"advertId": campaign_id, "days": days})


# --------------------------------------------------------------------------- #
# Which variant owns a day
# --------------------------------------------------------------------------- #


def test_a_day_fully_inside_one_exposure_belongs_to_it() -> None:
    """The ordinary case: the photo was live from before midnight to after."""
    windows = [ExposureWindow(VARIANT_A, _msk(2026, 8, 1, 9), _msk(2026, 8, 10, 9))]

    assert owner_of_day(windows, date(2026, 8, 5)) == VARIANT_A


def test_the_day_a_photo_is_swapped_belongs_to_nobody() -> None:
    """A split day is attributed to neither variant.

    WB's finest advertising grain is the calendar day, so the impressions of a
    swap day were served partly under each photo and cannot be divided. Giving
    them to either variant mixes exactly what the test is trying to separate.
    """
    windows = [
        ExposureWindow(VARIANT_A, _msk(2026, 8, 1, 9), _msk(2026, 8, 5, 9)),
        ExposureWindow(VARIANT_B, _msk(2026, 8, 5, 9), None),
    ]

    assert owner_of_day(windows, date(2026, 8, 5)) is None


def test_the_day_after_a_swap_belongs_to_the_new_variant() -> None:
    """Attribution resumes on the first full day of the new photo."""
    windows = [
        ExposureWindow(VARIANT_A, _msk(2026, 8, 1, 9), _msk(2026, 8, 5, 9)),
        ExposureWindow(VARIANT_B, _msk(2026, 8, 5, 9), None),
    ]

    assert owner_of_day(windows, date(2026, 8, 6)) == VARIANT_B


def test_a_day_before_the_test_started_belongs_to_nobody() -> None:
    """Days the card carried its own photo are not the test's data."""
    windows = [ExposureWindow(VARIANT_A, _msk(2026, 8, 5, 9), None)]

    assert owner_of_day(windows, date(2026, 8, 4)) is None


def test_a_still_live_variant_owns_every_full_day_since_activation() -> None:
    """An open-ended window keeps accruing days until something replaces it."""
    windows = [ExposureWindow(VARIANT_A, _msk(2026, 8, 1, 23), None)]

    assert owner_of_day(windows, date(2026, 8, 2)) == VARIANT_A
    assert owner_of_day(windows, date(2026, 8, 1)) is None  # activated mid-day


def test_a_variant_that_returns_for_a_second_round_owns_both_stretches() -> None:
    """Rotation may install the same photo again; both windows count."""
    windows = [
        ExposureWindow(VARIANT_A, _msk(2026, 8, 1, 9), _msk(2026, 8, 5, 9)),
        ExposureWindow(VARIANT_B, _msk(2026, 8, 5, 9), _msk(2026, 8, 9, 9)),
        ExposureWindow(VARIANT_A, _msk(2026, 8, 9, 9), None),
    ]

    assert owner_of_day(windows, date(2026, 8, 3)) == VARIANT_A
    assert owner_of_day(windows, date(2026, 8, 11)) == VARIANT_A


# --------------------------------------------------------------------------- #
# What a day's numbers are
# --------------------------------------------------------------------------- #


def test_metrics_match_the_wb_payload_summed_over_platforms_and_campaigns() -> None:
    """A variant-day equals the hand-summed fullstats rows for that nm.

    Two campaigns serve the same card on the same day across two platforms.
    The attributed row must be the total of all four buckets — reading a single
    ``nms[]`` row as "the day" understates every metric.
    """
    windows = [ExposureWindow(VARIANT_A, _msk(2026, 8, 1, 9), None)]
    campaigns = [
        _campaign(
            111,
            [
                {
                    "date": "2026-08-02",
                    "apps": [
                        {
                            "appType": 1,
                            "nms": [
                                _nm(
                                    NM_UNDER_TEST,
                                    views=1000,
                                    clicks=90,
                                    atbs=8,
                                    orders=3,
                                    sum=1500.0,
                                )
                            ],
                        },
                        {
                            "appType": 3,
                            "nms": [
                                _nm(
                                    NM_UNDER_TEST, views=500, clicks=40, atbs=5, orders=1, sum=700.0
                                )
                            ],
                        },
                    ],
                }
            ],
        ),
        _campaign(
            222,
            [
                _fullstats_day(
                    "2026-08-02",
                    [_nm(NM_UNDER_TEST, views=250, clicks=20, atbs=2, orders=1, sum=300.0)],
                )
            ],
        ),
    ]

    rows = attribute(campaigns, nm_id=NM_UNDER_TEST, windows=windows)

    assert len(rows) == 1
    row = rows[0]
    assert (row.variant_id, row.stat_date) == (VARIANT_A, date(2026, 8, 2))
    assert (row.views, row.clicks, row.atbs, row.orders) == (1750, 150, 15, 5)
    assert row.spend == Decimal("2500.00")


def test_another_skus_rows_are_not_counted() -> None:
    """A campaign advertising a sibling card contributes nothing to this test.

    WB books the size or colour the buyer actually converted on as its own
    ``nms[]`` row inside the same campaign-day. Those belong to a different
    card and would inflate this variant's orders for free.
    """
    windows = [ExposureWindow(VARIANT_A, _msk(2026, 8, 1, 9), None)]
    campaigns = [
        _campaign(
            111,
            [
                _fullstats_day(
                    "2026-08-02",
                    [
                        _nm(NM_UNDER_TEST, views=1000, clicks=90, atbs=8, orders=3),
                        _nm(SIBLING_NM, views=0, clicks=0, atbs=4, orders=9),
                    ],
                )
            ],
        )
    ]

    rows = attribute(campaigns, nm_id=NM_UNDER_TEST, windows=windows)

    assert [(row.views, row.clicks, row.atbs, row.orders) for row in rows] == [(1000, 90, 8, 3)]


def test_unattributable_days_are_dropped_not_zeroed() -> None:
    """A swap day produces no row at all, rather than a row of zeroes.

    A zero row would count as evidence that the photo earned nothing that day,
    which is the opposite of "we cannot tell".
    """
    windows = [
        ExposureWindow(VARIANT_A, _msk(2026, 8, 1, 9), _msk(2026, 8, 3, 9)),
        ExposureWindow(VARIANT_B, _msk(2026, 8, 3, 9), None),
    ]
    campaigns = [
        _campaign(
            111,
            [
                _fullstats_day("2026-08-02", [_nm(NM_UNDER_TEST, views=1000, clicks=90)]),
                _fullstats_day("2026-08-03", [_nm(NM_UNDER_TEST, views=1100, clicks=95)]),
                _fullstats_day("2026-08-04", [_nm(NM_UNDER_TEST, views=1200, clicks=99)]),
            ],
        )
    ]

    rows = attribute(campaigns, nm_id=NM_UNDER_TEST, windows=windows)

    assert [(row.stat_date, row.variant_id) for row in rows] == [
        (date(2026, 8, 2), VARIANT_A),
        (date(2026, 8, 4), VARIANT_B),
    ]


def test_a_day_with_no_rows_for_our_sku_is_not_attributed() -> None:
    """A campaign-day that never served this card yields no variant-day."""
    windows = [ExposureWindow(VARIANT_A, _msk(2026, 8, 1, 9), None)]
    campaigns = [_campaign(111, [_fullstats_day("2026-08-02", [_nm(SIBLING_NM, views=900)])])]

    assert attribute(campaigns, nm_id=NM_UNDER_TEST, windows=windows) == []
