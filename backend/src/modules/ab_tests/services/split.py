"""The same measurements, read once per advertising campaign.

A card is often pushed by two campaigns at once, and until the counters were
kept apart the page could only show their sum. The sum is still the headline —
a photo's total показов is what it got — but it is not a comparison: «Единая»
and «CPC» buy different traffic at different prices, and a campaign switched on
halfway through lifts every photo that follows it in a way that reads exactly
like one photo winning.

So each block of the page can be read through one campaign, and this module is
the projection that makes that possible. Three shapes come out of it, one per
question the page asks:

* :func:`campaign_totals` — «сколько принесла каждая РК», the branches under
  each figure of «Итог по тесту».
* :func:`variant_campaign_metrics` — the result table, computed inside one
  campaign. The leader is recomputed there too: the best CTR overall is not
  necessarily the best CTR in the campaign being looked at.
* :func:`exposure_campaign_counts` — what each turn earned from each campaign,
  which is what lets the timeline show only the laps a campaign actually ran
  for.

**A campaign appears only once it has earned something.** The register knows
every campaign the poller has read counters from, and a card can name a
campaign that never served it; a branch of zeroes is not a finding. This is
also what keeps the one-campaign case looking exactly as it did before the
split: one entry, and the page renders its old self.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from src.modules.ab_tests.models import (
    AbTestCampaign,
    AbTestVariant,
    VariantExposure,
    VariantStatWindow,
)
from src.modules.ab_tests.schemas import (
    CampaignTotals,
    ExposureCampaignCounts,
    VariantCampaignMetrics,
)
from src.modules.ab_tests.services.campaigns import (
    CampaignKind,
    display_name,
    sort_key,
)
from src.modules.ab_tests.services.metrics import conversions, totals_from_windows
from src.modules.ab_tests.services.rounds import gap_to_best, standings


@dataclass(frozen=True)
class CampaignRef:
    """One campaign as the page names it."""

    campaign_id: int
    name: str
    kind: str


def _counts(row: VariantStatWindow) -> tuple[int, int]:
    """One window's views and clicks."""
    return row.views, row.clicks


def campaigns_with_traffic(
    *, windows: Iterable[VariantStatWindow], registered: Sequence[AbTestCampaign]
) -> list[CampaignRef]:
    """Which campaigns this test actually measured, in the page's order.

    Args:
        windows: Every recorded interval of the test.
        registered: The register's rows, which carry the names and the kinds.

    Returns:
        One entry per campaign that has at least one window, ordered «Единая,
        Руч. поиск, Руч. полки, CPC» and then by id. A campaign with windows
        but no register row — the legacy ``0``, or one archived before it was
        ever named — is included without a kind rather than dropped: its
        traffic is on the page and has to be accounted for.
    """
    earned = {row.campaign_id for row in windows}
    known = {row.campaign_id: row for row in registered}

    refs = [
        CampaignRef(
            campaign_id=campaign_id,
            name=display_name(
                name=known[campaign_id].name if campaign_id in known else "",
                kind=known[campaign_id].kind if campaign_id in known else str(CampaignKind.UNKNOWN),
                campaign_id=campaign_id,
            ),
            kind=known[campaign_id].kind if campaign_id in known else str(CampaignKind.UNKNOWN),
        )
        for campaign_id in earned
    ]
    return sorted(refs, key=lambda ref: sort_key(ref.kind, ref.campaign_id))


def campaign_totals(
    *, windows: Sequence[VariantStatWindow], refs: Sequence[CampaignRef]
) -> list[CampaignTotals]:
    """Total what each campaign brought, over every photo and every turn.

    Summed from the same rows the whole-test figures are summed from, so the
    branches add up to the trunk — which is the property that makes the split
    checkable rather than decorative.

    Args:
        windows: Every recorded interval of the test.
        refs: The campaigns to report, already ordered.

    Returns:
        One entry per campaign, in the given order.
    """
    rows: list[CampaignTotals] = []
    for ref in refs:
        mine = [row for row in windows if row.campaign_id == ref.campaign_id]
        totals = totals_from_windows(_as_counts(mine))
        ratios = conversions(totals)
        rows.append(
            CampaignTotals(
                campaign_id=ref.campaign_id,
                name=ref.name,
                kind=ref.kind,
                views=totals.views,
                clicks=totals.clicks,
                atbs=totals.atbs,
                orders=totals.orders,
                spend=totals.spend,
                click_through=ratios.click_through,
                add_to_cart=ratios.add_to_cart,
                order_rate=ratios.order_rate,
            )
        )
    return rows


def variant_campaign_metrics(
    *,
    variants: Sequence[AbTestVariant],
    windows: Sequence[VariantStatWindow],
    exposures: Sequence[VariantExposure],
    refs: Sequence[CampaignRef],
) -> dict[uuid.UUID, list[VariantCampaignMetrics]]:
    """Per photo, what each campaign measured for it.

    Everything is recomputed inside the campaign — the ratios, the gap to the
    leader and the laps. That is the point: a photo can lead «Единая» and trail
    «CPC», and reading it against the whole test's leader would hide exactly
    that.

    Args:
        variants: The test's photos, in rotation order.
        windows: Every recorded interval of the test.
        exposures: The test's turns, which carry the lap numbers.
        refs: The campaigns to report.

    Returns:
        ``{variant_id: [metrics, one per campaign in order]}``.
    """
    by_variant: dict[uuid.UUID, list[VariantCampaignMetrics]] = {v.id: [] for v in variants}

    for ref in refs:
        mine = [row for row in windows if row.campaign_id == ref.campaign_id]
        per_variant = {
            variant.id: [row for row in mine if row.variant_id == variant.id]
            for variant in variants
        }
        ratios = {
            variant_id: conversions(totals_from_windows(_as_counts(rows)))
            for variant_id, rows in per_variant.items()
        }
        best = max(
            (r.click_through for r in ratios.values() if r.click_through is not None), default=None
        )
        laps = standings(
            variant_ids=[variant.id for variant in variants],
            windows=mine,
            exposures=exposures,
            played_from_windows=True,
        )

        for variant in variants:
            totals = totals_from_windows(_as_counts(per_variant[variant.id]))
            gap, result = gap_to_best(ratios[variant.id].click_through, best)
            by_variant[variant.id].append(
                VariantCampaignMetrics(
                    campaign_id=ref.campaign_id,
                    views=totals.views,
                    clicks=totals.clicks,
                    atbs=totals.atbs,
                    orders=totals.orders,
                    spend=totals.spend,
                    click_through=ratios[variant.id].click_through,
                    add_to_cart=ratios[variant.id].add_to_cart,
                    order_rate=ratios[variant.id].order_rate,
                    ctr_gap=gap,
                    ctr_result=result,
                    rounds_played=laps[variant.id].rounds_played,
                    rounds_won=laps[variant.id].rounds_won,
                )
            )
    return by_variant


def exposure_campaign_counts(
    *, exposure: VariantExposure, windows: Sequence[VariantStatWindow], refs: Sequence[CampaignRef]
) -> list[ExposureCampaignCounts]:
    """What one turn earned, split by campaign.

    Attributed exactly the way the turn's total is: a window belongs to the
    exposure that was open when it closed. Only campaigns that earned something
    in this turn are listed — the timeline reads «did this РК run in this lap»
    off the presence of an entry, and an entry of zeroes would answer yes.

    Args:
        exposure: The turn.
        windows: Every recorded interval of the test.
        refs: The campaigns to report.

    Returns:
        One entry per campaign with traffic in this turn, in the given order.
    """
    rows: list[ExposureCampaignCounts] = []
    for ref in refs:
        views = clicks = 0
        for window in windows:
            if window.campaign_id != ref.campaign_id:
                continue
            if window.variant_id != exposure.variant_id:
                continue
            if window.window_end < exposure.activated_at:
                continue
            if exposure.deactivated_at is not None and window.window_end > exposure.deactivated_at:
                continue
            gained = _counts(window)
            views += gained[0]
            clicks += gained[1]
        if not views and not clicks:
            continue
        rows.append(
            ExposureCampaignCounts(
                campaign_id=ref.campaign_id,
                views=views,
                clicks=clicks,
                click_through=conversions(
                    totals_from_windows([_Counts(views=views, clicks=clicks)])
                ).click_through,
            )
        )
    return rows


@dataclass(frozen=True)
class _Counts:
    """The minimum :func:`..services.metrics.totals_from_windows` reads."""

    views: int = 0
    clicks: int = 0
    atbs: int = 0
    orders: int = 0
    spend: Decimal = Decimal("0")


def _as_counts(rows: Sequence[VariantStatWindow]) -> list[_Counts]:
    """Persisted windows as the arithmetic's input type."""
    return [
        _Counts(
            views=row.views,
            clicks=row.clicks,
            atbs=row.atbs,
            orders=row.orders,
            spend=Decimal(row.spend),
        )
        for row in rows
    ]


__all__ = [
    "CampaignRef",
    "campaign_totals",
    "campaigns_with_traffic",
    "exposure_campaign_counts",
    "variant_campaign_metrics",
]
