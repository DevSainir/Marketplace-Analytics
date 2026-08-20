"""Turning ``/adv/v3/fullstats`` into per-variant advertising days.

Two rules, both of which exist because WB's advertising grain is coarser than
the rotation's:

**Whole days only.** WB reports one row per calendar day (Moscow time) and
nothing finer. A day during which the photo was swapped was served under two
different images, so it belongs to neither variant and is dropped. Crediting it
to either one mixes the arms the test exists to separate; recording it as a zero
day would be worse still, since zero is evidence and "unknown" is not.

**Sum the whole campaign-day for our nm.** fullstats splits a campaign-day
across platforms (``apps[]``) and across every SKU the campaign touched
(``nms[]``), including sibling sizes/colours booked with ``views = clicks = 0``.
A variant's day is the sum over platforms and campaigns of the rows for *its
own* nm — see ``references/advertising.md`` in the ``wildberries-api`` skill.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Protocol

from src.core.timeutils import MOSCOW_TZ
from src.integrations.wildberries.schemas.advertising import WBAdvCampaignStats


@dataclass(frozen=True)
class ExposureWindow:
    """A stretch during which one variant was the card's main photo.

    Attributes:
        variant_id: The photo that was live.
        activated_at: When WB accepted the media upload (tz-aware).
        deactivated_at: When it was replaced; ``None`` while still live.
    """

    variant_id: uuid.UUID
    activated_at: datetime
    deactivated_at: datetime | None


@dataclass(frozen=True)
class AttributedDay:
    """One advertising day credited to one variant."""

    variant_id: uuid.UUID
    stat_date: date
    views: int
    clicks: int
    atbs: int
    orders: int
    spend: Decimal


def _moscow_midnight(day: date) -> datetime:
    """Start of ``day`` in Moscow time — WB's advertising day boundary."""
    return datetime.combine(day, time.min, tzinfo=MOSCOW_TZ)


def owner_of_day(windows: Sequence[ExposureWindow], stat_date: date) -> uuid.UUID | None:
    """Return the variant that was live for the whole of ``stat_date``.

    Args:
        windows: The test's exposure history, in any order.
        stat_date: The advertising day to attribute (Moscow time).

    Returns:
        The variant id, or ``None`` when no single variant covered the entire
        day — a swap day, a paused stretch, or a day before the test started.
    """
    day_start = _moscow_midnight(stat_date)
    day_end = _moscow_midnight(stat_date + timedelta(days=1))

    for window in windows:
        if window.activated_at > day_start:
            continue
        if window.deactivated_at is not None and window.deactivated_at < day_end:
            continue
        return window.variant_id
    return None


class DailyCounts(Protocol):
    """Any pre-summed advertising day — WB's, ours, or the monitoring module's.

    Read-only members, so a ``NamedTuple`` (which is what the monitoring
    contract returns) structurally satisfies it.
    """

    @property
    def stat_date(self) -> date: ...

    @property
    def views(self) -> int: ...

    @property
    def clicks(self) -> int: ...

    @property
    def atbs(self) -> int: ...

    @property
    def orders(self) -> int: ...

    @property
    def spend(self) -> Decimal: ...


def attribute_days(
    days: Iterable[DailyCounts], *, windows: Sequence[ExposureWindow]
) -> list[AttributedDay]:
    """Credit already-summed advertising days to the variants that owned them.

    The counterpart to :func:`attribute` for rows that were summed upstream —
    the monitoring module's ``load_ad_days_for_nm`` returns exactly this shape,
    which is how a test reads advertising without paying fullstats' toll a
    second time.

    Args:
        days: One row per calendar day, already summed over campaigns and
            platforms for the SKU under test.
        windows: The test's exposure history.

    Returns:
        One row per attributable day, ascending by date; days no single variant
        owned in full are absent.
    """
    rows: list[AttributedDay] = []
    for day in sorted(days, key=lambda item: item.stat_date):
        variant_id = owner_of_day(windows, day.stat_date)
        if variant_id is None:
            continue
        rows.append(
            AttributedDay(
                variant_id=variant_id,
                stat_date=day.stat_date,
                views=day.views,
                clicks=day.clicks,
                atbs=day.atbs,
                orders=day.orders,
                spend=Decimal(day.spend).quantize(Decimal("0.01")),
            )
        )
    return rows


def attribute(
    campaigns: Sequence[WBAdvCampaignStats],
    *,
    nm_id: int,
    windows: Sequence[ExposureWindow],
) -> list[AttributedDay]:
    """Fold a fullstats response into per-variant advertising days.

    Args:
        campaigns: Parsed ``/adv/v3/fullstats`` campaign nodes, any number.
        nm_id: The SKU under test; rows for every other SKU are ignored.
        windows: The test's exposure history.

    Returns:
        One row per attributable day, ascending by date. Days no variant owned
        in full, and days on which this SKU was not served, are absent.
    """
    per_day: dict[date, dict[str, Decimal | int]] = {}

    for campaign in campaigns:
        for day in campaign.days:
            for app in day.apps:
                for row in app.nms:
                    if row.nm_id != nm_id:
                        continue
                    bucket = per_day.setdefault(
                        day.stat_date,
                        {"views": 0, "clicks": 0, "atbs": 0, "orders": 0, "spend": Decimal("0")},
                    )
                    bucket["views"] = int(bucket["views"]) + row.views
                    bucket["clicks"] = int(bucket["clicks"]) + row.clicks
                    bucket["atbs"] = int(bucket["atbs"]) + row.atbs
                    bucket["orders"] = int(bucket["orders"]) + row.orders
                    bucket["spend"] = Decimal(bucket["spend"]) + Decimal(str(row.sum))

    rows: list[AttributedDay] = []
    for stat_date in sorted(per_day):
        variant_id = owner_of_day(windows, stat_date)
        if variant_id is None:
            continue
        bucket = per_day[stat_date]
        rows.append(
            AttributedDay(
                variant_id=variant_id,
                stat_date=stat_date,
                views=int(bucket["views"]),
                clicks=int(bucket["clicks"]),
                atbs=int(bucket["atbs"]),
                orders=int(bucket["orders"]),
                spend=Decimal(bucket["spend"]).quantize(Decimal("0.01")),
            )
        )
    return rows
