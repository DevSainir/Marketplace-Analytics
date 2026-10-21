"""Ingestion of daily seller/customer price snapshots.

The customer side has two possible answers and they are not the same
measurement, so which one was used is written down beside the number:

* ``storefront`` — the shelf price for one fixed region, read at the moment the
  harvest ran. What this column always meant until 2026-09-22.
* ``orders`` — the modal price customers were actually charged that day. Used
  when the storefront cannot answer, which since 2026-09-22 is every day.

Measured 2026-09-22, the two agree closely but not exactly: ratio 1,0013,
median gap 5 ₽. The exact-match rate is low (31 %) for a reason that is not
error — the storefront was sampled once, in the morning, and WB moves the SPP
grid during the day.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from src.core.logging import get_logger
from src.integrations.wildberries.schemas import WBCardProduct, WBOrderPrice, WBPriceGood
from src.modules.monitoring.repos import PriceRepository

logger = get_logger(__name__)

#: Written into ``customer_source`` so a reader can tell the two apart.
_FROM_STOREFRONT = "storefront"
_FROM_ORDERS = "orders"


def _modal_prices(
    orders: list[WBOrderPrice],
    *,
    snapshot_date: date,
    regions: tuple[str, ...],
) -> dict[int, tuple[float, float | None]]:
    """Reduce one day's ordered lines to ``{nm_id: (price, spp)}``.

    The day's orders for a SKU are not one number: SPP is regional, so the rows
    carry several. The comparable subset is the regions the storefront's fixed
    ``dest`` stands for; when a SKU sold nowhere in them, every region is used
    rather than dropping the SKU — a price from the wrong region beats no price,
    and the difference is small (measured 2026-09-22: restricting to the fixed
    region moved agreement with the storefront from 31,4 % to 37,8 %, so region
    is a refinement here, not the mechanism).

    Cancelled lines are excluded to match how the agreement above was measured.

    Args:
        orders: Ordered lines from the statistics feed, any dates.
        snapshot_date: The day being snapshotted; other days are ignored.
        regions: Delivery regions comparable to the configured storefront dest.

    Returns:
        One ``(customer_price, spp)`` per SKU that sold on the day.
    """
    on_day = [
        order
        for order in orders
        if not order.is_cancel
        and order.finished_price > 0
        and order.ordered_at.date() == snapshot_date
    ]
    by_sku: dict[int, list[WBOrderPrice]] = {}
    for order in on_day:
        by_sku.setdefault(order.nm_id, []).append(order)

    resolved: dict[int, tuple[float, float | None]] = {}
    for nm_id, rows in by_sku.items():
        comparable = [row for row in rows if row.region_name in regions] or rows
        price = Counter(row.finished_price for row in comparable).most_common(1)[0][0]
        # The SPP is only reported for the price it belongs to, so it is taken
        # from the rows that carry that price rather than from the day at large.
        spps = [row.spp for row in comparable if row.finished_price == price and row.spp > 0]
        resolved[nm_id] = (price, Counter(spps).most_common(1)[0][0] if spps else None)
    return resolved


class PriceIngestion:
    """Persists the daily per-SKU seller/customer price snapshot."""

    def __init__(self, price_repo: PriceRepository) -> None:
        """Inject the price repository used for persistence."""
        self._prices = price_repo

    async def ingest_prices(
        self,
        goods: list[WBPriceGood],
        customer: list[WBCardProduct],
        *,
        snapshot_date: date,
        nm_ids: list[int] | None = None,
        order_prices: list[WBOrderPrice] | None = None,
        regions: tuple[str, ...] = (),
    ) -> int:
        """Persist a daily seller/customer price snapshot per SKU.

        Joins the seller ``discountedPrice`` (Prices & Discounts API) with the
        final customer price by ``nm_id`` into one row per SKU
        for ``snapshot_date``. A SKU present in only one source still yields a
        row (the missing side is ``NULL``); the matrix prices only these exact
        snapshot days — days without a snapshot stay unpriced.

        Snapshots are written ONLY for ``nm_ids`` — the SKUs this harvest
        covered. This matters for a single-SKU refresh: the seller ``goods`` feed
        returns the whole account, but the customer feed is fetched only for the
        harvested SKUs, so writing every good would stamp ``NULL`` customer
        prices over the other SKUs' snapshots. When ``nm_ids`` is ``None`` (a
        full harvest that did not scope), every good is written.

        Args:
            goods: Raw seller pricing records from the prices client.
            customer: Raw storefront card products from the card client.
            snapshot_date: The Moscow-time calendar day the snapshot represents.
            nm_ids: The harvested SKUs to snapshot; ``None`` writes all goods.
            order_prices: Ordered lines to fall back on when the storefront did
                not answer for a SKU; ``None`` or empty leaves those customer
                prices ``NULL``, exactly as before this fallback existed.
            regions: Delivery regions comparable to the configured storefront
                ``dest`` — see :func:`_modal_prices`.

        Returns:
            The number of price snapshot rows persisted.
        """
        seller_by_sku = {good.nm_id: good.seller_price for good in goods}
        currency_by_sku = {good.nm_id: good.currency[:8] for good in goods}
        customer_by_sku = {product.nm_id: product.customer_price for product in customer}
        ordered_by_sku = _modal_prices(
            order_prices or [], snapshot_date=snapshot_date, regions=regions
        )

        target_ids = (
            sorted(nm_ids)
            if nm_ids is not None
            else sorted(seller_by_sku.keys() | customer_by_sku.keys() | ordered_by_sku.keys())
        )

        rows: list[dict[str, object]] = []
        from_orders = 0
        for nm_id in target_ids:
            seller = seller_by_sku.get(nm_id)
            storefront = customer_by_sku.get(nm_id)
            if storefront is not None:
                customer_price: float | None = storefront
                spp: float | None = None
                source: str | None = _FROM_STOREFRONT
            elif nm_id in ordered_by_sku:
                customer_price, spp = ordered_by_sku[nm_id]
                source = _FROM_ORDERS
                from_orders += 1
            else:
                customer_price, spp, source = None, None, None
            if seller is None and customer_price is None:
                continue
            rows.append(
                {
                    "stat_date": snapshot_date,
                    "nm_id": nm_id,
                    "seller_price": seller,
                    "customer_price": customer_price,
                    "customer_spp": spp,
                    "customer_source": source,
                    "currency": currency_by_sku.get(nm_id, ""),
                }
            )

        count = await self._prices.upsert_many(rows)
        logger.info(
            "Ingested %d price snapshot rows for %s (%d customer prices from orders).",
            count,
            snapshot_date,
            from_orders,
        )
        return count

    async def fill_missing_from_orders(
        self,
        order_prices: list[WBOrderPrice],
        *,
        snapshot_date: date,
        nm_ids: list[int],
        regions: tuple[str, ...] = (),
    ) -> int:
        """Fill the day's EMPTY customer prices from orders, touching nothing else.

        The top-up pass. A full harvest writes the whole snapshot; this writes
        only the holes, because the reason the holes exist is timing: the order
        feed answers for a SKU once it has sold that day, so a morning harvest
        finds fewer SKUs than an evening one. Re-running the whole snapshot to
        catch up would rewrite prices that are already correct and spend every
        other WB source to do it.

        "Only the holes" is enforced by the UPDATE itself, not by this loop —
        see :meth:`~src.modules.monitoring.repos.prices.PriceRepository.
        fill_missing_customer_price`.

        Args:
            order_prices: Ordered lines witnessing today's prices.
            snapshot_date: The day being topped up.
            nm_ids: The SKUs known to be missing a price; others are ignored
                even when the orders could answer for them.
            regions: Delivery regions comparable to the storefront ``dest``.

        Returns:
            The number of snapshot rows actually filled.
        """
        modal = _modal_prices(order_prices, snapshot_date=snapshot_date, regions=regions)
        filled = 0
        for nm_id in nm_ids:
            answer = modal.get(nm_id)
            if answer is None:
                continue
            price, spp = answer
            if await self._prices.fill_missing_customer_price(
                stat_date=snapshot_date,
                nm_id=nm_id,
                customer_price=price,
                spp=spp,
                source=_FROM_ORDERS,
            ):
                filled += 1
        logger.info(
            "Topped up %d of %d missing customer prices for %s.",
            filled,
            len(nm_ids),
            snapshot_date,
        )
        return filled
