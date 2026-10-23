"""The catalogue: what `guide` captures, how often, and why it is worth a row.

This is the file to read first and the only one to edit when adding a feed. Each
entry carries the measurement that justifies its cadence — every window here was
probed against WB on 2026-09-12, and each entry states what was found.

**The cadence rule.** Daily when a missed day is a lost day: the feed's window is
short enough that falling behind cannot be made up. Monthly for everything else,
because these feeds serve the account's whole history and a late read costs
nothing. There is deliberately no weekly cadence — the only feed that ever
warranted one (FBS supplies, ~31 days) turned out not to be worth capturing at
all; see below.

What is deliberately NOT here: KIZ codes (fiscal receipt numbers), advertising
top-ups and write-offs (the second duplicates ``fullstats.spend``), balances
(WB serves no history, so there is nothing to capture), the deleted-card bin,
buyer chat, and the FBS orders feed (``supplier/orders`` already carries FBS
orders — measured: a share of its rows came from the seller's own warehouse). Each was
considered and rejected; re-proposing one should come with a use for it.

**FBS supplies (`marketplace /api/v3/supplies`) were built and then removed**,
2026-09-14, and the reason is worth keeping so nobody adds them again. The feed
is a shipment header with no contents: id, auto-generated name, created/closed
timestamps, a numeric destination office, and `scanDt` filled on a minority of
rows.
The contents are unreachable — `/supplies/{id}/orders` is 404, `/trbx` returns
boxes with an empty order list, and `/api/v3/orders?supplyId=` IGNORES the
filter (asked for one supply, got a row from another). And the ids join to
nothing we hold: settlement `gi_id` and supply ids live in ranges far apart —
different entities behind the same `WB-GI-` prefix, zero overlap on every
supply. What survives is a list of dates and office
numbers that answers one question nobody asked. If FBS shipments ever matter,
the feed to capture is `/api/v3/orders` (60-day window), which carries
`supplyId` on each order.
"""

from __future__ import annotations

import enum
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass

from src.core.config import Settings
from src.integrations.wildberries.clients.reference import WBReferenceClient
from src.modules.guide.services.fetch import (
    CaptureBatch,
    CaptureWindow,
    fetch_acceptance_report,
    fetch_claims,
    fetch_documents,
    fetch_feedbacks,
    fetch_goods_return,
    fetch_orders,
    fetch_questions,
    fetch_region_sale,
    fetch_tariffs_pallet,
    fetch_tariffs_return,
)


class GuideCadence(enum.StrEnum):
    """How often a source is walked. One Celery task per value."""

    DAILY = "daily"
    MONTHLY = "monthly"


@dataclass(frozen=True, slots=True)
class GuideSource:
    """One captured feed.

    Attributes:
        key: Stored in ``guide_record.source``. Never rename one — it is the
            join between the rows already captured and the code that captured
            them.
        title: Human-readable label, for logs and for whoever reads this later.
        cadence: Which scheduled task walks it.
        base_url: Attribute on :class:`~src.core.config.Settings` naming the WB
            host. An attribute rather than a literal so a host move stays a
            config change.
        tokens: Bundle fields to try in order; the first non-empty one is used.
            A tuple because the tariff feeds are account-independent and any
            seller token answers them, while the rest need one specific scope.
        fetch: The walk. Takes a client and the previous watermark, and YIELDS
            batches — each one a slice small enough to hold, carrying the
            watermark it makes safe. Never a whole run at once: see
            :class:`~src.modules.guide.services.fetch.common.CaptureBatch`.
        why: What this would be for, the day someone asks. Written now because
            the answer is much harder to reconstruct later.
        retention: What WB will still serve, as measured. The cadence is only
            defensible next to this number.
    """

    key: str
    title: str
    cadence: GuideCadence
    base_url: str
    tokens: tuple[str, ...]
    fetch: Callable[[WBReferenceClient, CaptureWindow], AsyncIterator[CaptureBatch]]
    why: str
    retention: str

    def token_for(self, bundle: object) -> str:
        """First non-empty token among :attr:`tokens`, or an empty string."""
        for field in self.tokens:
            value = getattr(bundle, field, "")
            if value:
                return str(value)
        return ""

    def host(self, settings: Settings) -> str:
        """Resolve the WB host for this source from settings."""
        return str(getattr(settings, self.base_url))


#: Any seller token answers the tariff calendar — it is the same for every
#: account on the platform.
_ANY_TOKEN: tuple[str, ...] = ("statistics", "analytics", "content")


GUIDE_SOURCES: tuple[GuideSource, ...] = (
    # ---- daily: the window closes faster than a month -------------------
    GuideSource(
        key="claims",
        title="Buyer return claims",
        cadence=GuideCadence.DAILY,
        base_url="wb_returns_base_url",
        tokens=("returns",),
        fetch=fetch_claims,
        why=(
            "The only source of a return's reason in the buyer's own words. "
            "A return in sale_record is money, goods-return is logistics; "
            "neither says why the item did not suit."
        ),
        retention=(
            "14 days. Measured on three accounts on 2026-09-12: on all of them the "
            "oldest claim is from 2026-08-29. The shortest window of anything "
            "WB serves."
        ),
    ),
    GuideSource(
        key="orders",
        title="Order feed",
        cadence=GuideCadence.DAILY,
        base_url="wb_statistics_base_url",
        tokens=("statistics",),
        fetch=fetch_orders,
        why=(
            "Canceled orders never reach the settlement report: it holds only "
            "buyouts and no cancellations at all. Cancellations are demand we "
            "simply do not see today. Plus the region and the order-to-buyout "
            "time, unit by unit."
        ),
        retention=(
            "188 days by order date (flag=1: 2026-03-08 is served, 2026-03-07 "
            "is empty), 181 days by the lastChangeDate cursor. One answer is cut "
            "off at 80,000 rows, so the walk is paged."
        ),
    ),
    # ---- monthly: WB serves the whole history -----------------------------
    GuideSource(
        key="region_sale",
        title="Sales by region",
        cadence=GuideCadence.MONTHLY,
        base_url="wb_analytics_base_url",
        tokens=("analytics",),
        fetch=fetch_region_sale,
        why=(
            "City and cost of sale broken down by geography. The order feed "
            "gives the region, but only 188 days back; this is the history since "
            "the first sale — the only way to look at geography further back."
        ),
        retention="No cut-off: served 2024-01 when measured. Request window 31 days.",
    ),
    GuideSource(
        key="goods_return",
        title="Product returns",
        cadence=GuideCadence.MONTHLY,
        base_url="wb_analytics_base_url",
        tokens=("analytics",),
        fetch=fetch_goods_return,
        why=(
            "Return logistics: where it is going, in what status, when it finished. "
            "Not the same as a return in sale_record (money), nor the same as "
            "a buyer claim (a complaint)."
        ),
        retention="No cut-off: served 2024-01. Request window 31 days.",
    ),
    GuideSource(
        key="acceptance",
        title="Paid acceptance",
        cadence=GuideCadence.MONTHLY,
        base_url="wb_analytics_base_url",
        tokens=("analytics",),
        fetch=fetch_acceptance_report,
        why=(
            "The settlement report carries acceptance only as a total. What "
            "accepting one particular supply cost, only this report says."
        ),
        retention=(
            "No cut-off: served 400 days back. Window 31 days, the report is async "
            "(create → poll → download), an empty window answers 204."
        ),
    ),
    # Answered reviews verbatim, text included. The daily rating and review-state
    # history (which reviews vanished, were rescored or excluded) is a separate,
    # structured record in `monitoring` — see monitoring/models/reviews.py.
    GuideSource(
        key="feedbacks",
        title="Reviews",
        cadence=GuideCadence.MONTHLY,
        base_url="wb_feedbacks_base_url",
        tokens=("feedbacks",),
        fetch=fetch_feedbacks,
        why=(
            "Rating over time and the text of complaints per SKU. No other "
            "source says why the funnel sagged after a change of batch."
        ),
        retention=(
            "Since the account began: the first reviews arrive within days of "
            "the first settlement report. No cut-off."
        ),
    ),
    GuideSource(
        key="questions",
        title="Buyer questions",
        cadence=GuideCadence.MONTHLY,
        base_url="wb_feedbacks_base_url",
        tokens=("feedbacks",),
        fetch=fetch_questions,
        why=(
            "What the product card is missing: what buyers ask about is not in "
            "the description. Weaker than reviews, but fetched with the same token "
            "and the same walk."
        ),
        retention="Since the account began, like reviews.",
    ),
    GuideSource(
        key="documents",
        title="Documents: universal transfer documents, acts, reports",
        cadence=GuideCadence.MONTHLY,
        base_url="wb_documents_base_url",
        tokens=("documents",),
        fetch=fetch_documents,
        why="An inventory of signed originals: which documents WB has issued at all is here.",
        retention="Since the account began: served 2023-10-30. Page of 50.",
    ),
    GuideSource(
        key="tariffs_pallet",
        title="Pallet tariffs",
        cadence=GuideCadence.MONTHLY,
        base_url="wb_common_base_url",
        tokens=_ANY_TOKEN,
        fetch=fetch_tariffs_pallet,
        why=(
            "Pallet tariffs by warehouse. If stock ever ships by the pallet, "
            "the tariff history will be needed, and WB serves only "
            "~70 days of it."
        ),
        retention=(
            "~70 days: 2026-07-04 serves 12 warehouses, 2026-06-29 is empty. "
            "A monthly pass takes the whole window with room to spare."
        ),
    ),
    GuideSource(
        key="tariffs_return",
        title="Return tariffs",
        cadence=GuideCadence.MONTHLY,
        base_url="wb_common_base_url",
        tokens=_ANY_TOKEN,
        fetch=fetch_tariffs_return,
        why="Reverse logistics price by warehouse — the second half of what a return costs.",
        retention="~70 days, the same limit as pallets: 2026-07-04 is there, 2026-06-29 is not.",
    ),
)


def sources_for(cadence: GuideCadence) -> Sequence[GuideSource]:
    """Every source one scheduled task is responsible for."""
    return tuple(source for source in GUIDE_SOURCES if source.cadence is cadence)


__all__ = [
    "GUIDE_SOURCES",
    "CaptureBatch",
    "CaptureWindow",
    "GuideCadence",
    "GuideSource",
    "sources_for",
]
