"""Canned WildBerries API response envelopes.

One place to keep the *real* upstream shapes — not the shapes the code wishes
WB used. Every builder here follows the shape of an observed response (the
values are synthetic), which is what makes them the single source of truth for
the integration tier's mock transport.

Every builder returns a plain ``dict``/``list`` so a test can mutate one field
to drive a specific edge case without rebuilding the whole envelope.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def goods_filter_page(
    *,
    goods: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a ``GET /api/v2/list/goods/filter`` envelope (Prices & Discounts).

    Args:
        goods: Explicit ``listGoods`` rows; one plausible row when omitted.

    Returns:
        The full ``{"data": {"listGoods": [...]}}`` envelope.
    """
    return {"data": {"listGoods": goods if goods is not None else [price_good()]}}


def price_good(
    *,
    nm_id: int = 953770957,
    discounted_price: float = 1490.0,
    discount: int = 25,
) -> dict[str, Any]:
    """Build one ``listGoods`` row.

    Args:
        nm_id: WB SKU identifier.
        discounted_price: Seller price after the seller's own discount, ₽.
        discount: The seller discount percentage.

    Returns:
        A single goods row in the shape WB returns.
    """
    return {
        "nmID": nm_id,
        "vendorCode": f"M-TEST-{nm_id}",
        "discount": discount,
        "sizes": [{"sizeID": 0, "price": 1990, "discountedPrice": discounted_price}],
    }


def card_detail(nm_ids: list[int], *, price_kopecks: int = 119_000) -> dict[str, Any]:
    """Build a ``card.wb.ru /cards/v4/detail`` envelope (customer prices).

    Args:
        nm_ids: The SKUs the storefront returns.
        price_kopecks: Final customer price in kopecks (WB's unit here).

    Returns:
        The ``{"data": {"products": [...]}}`` envelope.
    """
    return {
        "data": {
            "products": [
                {"id": nm_id, "sizes": [{"price": {"product": price_kopecks}}]} for nm_id in nm_ids
            ]
        }
    }


def sale_record(
    *,
    nm_id: int = 953770957,
    sale_date: str = "2026-07-01T12:00:00",
    srid: str = "srid-1",
    is_return: bool = False,
) -> dict[str, Any]:
    """Build one ``/api/v1/supplier/sales`` row (sale-date buyouts).

    Args:
        nm_id: WB SKU identifier.
        sale_date: WB's local-time timestamp string.
        srid: The WB shipment id — the row's natural key.
        is_return: ``True`` renders a return (negative ``saleID`` prefix ``R``).

    Returns:
        A single supplier-sales row.
    """
    return {
        "date": sale_date,
        "lastChangeDate": sale_date,
        "nmId": nm_id,
        "srid": srid,
        "saleID": f"{'R' if is_return else 'S'}9993000000",
        "forPay": -500.0 if is_return else 500.0,
        "priceWithDisc": 1490.0,
        "warehouseName": "Коледино",
    }


def funnel_history_row(
    *,
    nm_id: int = 953770957,
    day: date = date(2026, 7, 1),
    open_card: int = 1000,
    add_to_cart: int = 120,
    orders: int = 40,
) -> dict[str, Any]:
    """Build one ``/api/analytics/v3/sales-funnel/products/history`` row.

    This is the verified daily funnel source (the aggregate endpoint is the
    cohort source — see the ``buyout-percent-cohort-pipeline`` note).

    Args:
        nm_id: WB SKU identifier.
        day: The Moscow calendar day the metrics belong to.
        open_card: Card opens that day.
        add_to_cart: Add-to-cart events that day.
        orders: Ordered items that day.

    Returns:
        One funnel history row.
    """
    return {
        "nmID": nm_id,
        "dt": day.isoformat(),
        "openCardCount": open_card,
        "addToCartCount": add_to_cart,
        "ordersCount": orders,
        "buyoutsCount": 0,
        "cancelCount": 0,
    }


def rate_limited_headers(*, retry_after_seconds: int) -> dict[str, str]:
    """Headers for a WB 429 that names an explicit wait.

    Args:
        retry_after_seconds: The delta-seconds value WB demands.

    Returns:
        A ``Retry-After`` header mapping.
    """
    return {"Retry-After": str(retry_after_seconds)}


def wb_ratelimit_headers(*, retry_seconds: int) -> dict[str, str]:
    """Headers for the statistics surface's own limiter header.

    WB's statistics API answers with ``X-Ratelimit-Retry`` instead of the
    standard ``Retry-After``; the client honours both.

    Args:
        retry_seconds: The delta-seconds value WB demands.

    Returns:
        An ``X-Ratelimit-Retry`` header mapping.
    """
    return {"X-Ratelimit-Retry": str(retry_seconds)}
