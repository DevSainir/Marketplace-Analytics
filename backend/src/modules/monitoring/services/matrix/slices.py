"""Shared value objects and numeric helpers of the matrix package.

:class:`_AdSlice` and :class:`_BucketAcc` are the package-internal currency
every matrix stage trades in: a campaign-day's advertising metrics (or a zone
slice of them) and the per-(day, bucket) accumulator such slices are folded
into. The tiny numeric helpers live here too so every stage rounds and guards
division-by-zero the same way.

Both carry the campaign's numbers as their primary metrics — an advertising
column measures an ad campaign, not the card on screen — with the viewed
card's own share alongside in :class:`_SkuSlice`, which is what "Overall" and
"Organic" are built from and what the carts/orders hover splits out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class _SkuSlice:
    """The viewed card's own share of an advertising slice.

    An advertising column is the campaign's, but two columns are the CARD's:
    "Overall" (its whole day) and "Organic" (that day minus what the ads
    brought). Both would be wrong if built from a campaign's totals — a
    campaign promoting several cards would lend this one the others' spend, and
    "Organic" would subtract orders never booked on it. So the card's own
    slice rides along, split across zones by its own search rows.
    """

    views: int = 0
    clicks: int = 0
    add_to_cart: int = 0
    spend: float = 0.0
    orders: int = 0

    def add(self, piece: _SkuSlice) -> None:
        """Fold another card-slice into this one."""
        self.views += piece.views
        self.clicks += piece.clicks
        self.add_to_cart += piece.add_to_cart
        self.spend += piece.spend
        self.orders += piece.orders


@dataclass
class _AdSlice:
    """Advertising metrics of one campaign-day (or a zone slice of it).

    Every metric here is the CAMPAIGN's, summed across all its nm_ids: the
    matrix's advertising columns measure an ad campaign, so a conversion
    it paid for counts whichever size/colour variant the buyer finally picked
    (WB's "associated conversions" — WB books the conversion on the variant, not
    on the advertised card).

    ``order_sum`` is ``None`` when the slice's revenue cannot be attributed to
    its zone (a split campaign) — the taint propagates to the bucket.

    ``traffic_add_to_cart``/``traffic_orders`` are the part of those conversions
    that came with traffic (the advertised card's own rows). WB books an
    associated variant's conversions with ``views=clicks=0``, so what the two
    pairs differ by is exactly the associative extra — the conversions no report
    attributes to a display zone, and which splitting a campaign-day therefore
    has to apportion.

    ``sku`` is the viewed card's own share (see :class:`_SkuSlice`).

    ``campaign_id`` is set on a campaign-day's WHOLE slice (its zone legs do not
    need it): it is what the matrix header links to.

    ``currency`` is what the campaign is billed in (``""`` when never recorded);
    its zone legs inherit it.

    ``assoc_skus`` names the variants behind the conversion totals (``nm_id`` →
    ``(carts, orders)``), always summing to them. ``assoc_exact`` says whether
    those per-variant counts are harvested fact or apportionment: splitting a
    campaign-day across zones divides the associated variants' counts by
    estimate (see :func:`~src.modules.monitoring.services.matrix.assoc._split_assoc_skus`),
    except where a zone took none of the extra — or all of it — and the
    division is forced.
    """

    views: int = 0
    clicks: int = 0
    add_to_cart: int = 0
    spend: float = 0.0
    orders: int = 0
    order_sum: float | None = 0.0
    traffic_add_to_cart: int = 0
    traffic_orders: int = 0
    sku: _SkuSlice = field(default_factory=_SkuSlice)
    assoc_skus: dict[int, tuple[int, int]] = field(default_factory=dict)
    assoc_exact: bool = True
    campaign_id: int | None = None
    currency: str = ""


@dataclass
class _BucketAcc:
    """Accumulated advertising metrics of one (day, bucket) cell.

    The campaign's numbers (see :class:`_AdSlice`), with the viewed card's own
    share in ``sku``. ``currencies`` collects what each folded campaign is
    billed in — two codes when campaigns of both currencies share the cell.
    """

    views: int = 0
    clicks: int = 0
    add_to_cart: int = 0
    spend: float = 0.0
    orders: int = 0
    order_sum: float | None = 0.0
    sku: _SkuSlice = field(default_factory=_SkuSlice)
    assoc_skus: dict[int, tuple[int, int]] = field(default_factory=dict)
    assoc_exact: bool = True
    currencies: set[str] = field(default_factory=set)

    def add(self, piece: _AdSlice) -> None:
        """Fold a campaign slice into the bucket (revenue taint propagates)."""
        self.views += piece.views
        self.clicks += piece.clicks
        self.add_to_cart += piece.add_to_cart
        self.spend += piece.spend
        self.orders += piece.orders
        self.currencies.add(piece.currency)
        self.sku.add(piece.sku)
        # One estimated slice taints the whole cell's breakdown: the listed
        # variants would no longer sum to the number the cell shows.
        self.assoc_exact = self.assoc_exact and piece.assoc_exact
        for nm_id, (carts, orders) in piece.assoc_skus.items():
            prior_carts, prior_orders = self.assoc_skus.get(nm_id, (0, 0))
            self.assoc_skus[nm_id] = (prior_carts + carts, prior_orders + orders)
        if piece.order_sum is None:
            self.order_sum = None
        elif self.order_sum is not None:
            self.order_sum += piece.order_sum


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    """Numerator / denominator, or ``None`` when it cannot be computed."""
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator, 2)


def _percent(numerator: float | None, denominator: float | None) -> float | None:
    """Numerator / denominator as a percentage, or ``None`` on ÷0."""
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator * 100, 2)


def _day_range(date_from: date, date_to: date) -> list[date]:
    """Inclusive day sequence ``date_from..date_to``."""
    return [date_from + timedelta(days=offset) for offset in range((date_to - date_from).days + 1)]
