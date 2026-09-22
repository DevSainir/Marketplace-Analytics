"""Synthetic WildBerries clients for LOCAL development (``WB_FAKE_HARVEST``).

Drop-in stand-ins for the real HTTP clients that make **no** network request and
instead return deterministic, plausible payloads. They let the whole harvest →
ingest → dashboard pipeline run locally without spending WB's tiny rate budget
(the analytics surface allows ~3 requests per 20s per token; a full harvest plus
a 22-day cohort pass exhausts it repeatedly).

Two properties are load-bearing:

* **Deterministic.** Every figure is a pure function of ``(nm_id, day)`` via
  :func:`_seed`, so the same SKU shows the same series on every refresh — a
  moving target is useless for debugging a chart. No randomness, no clock.
* **Same interface.** Each class subclasses its real counterpart and overrides
  only the fetch methods and the async-context plumbing, so the harvest task
  calls them exactly as it calls the real clients. The gate that swaps them in
  lives in :mod:`src.integrations.wildberries.factory`; the task code is
  identical between local and prod.

Deliberately synthesised: funnel history, stocks, seller prices, and customer
(storefront) prices — the facts that drive «Заказы»/«Выкупы»/«Остатки»/«СПП».
Deliberately empty: advertising and the account-wide sales feed (their absence
is a valid state the pipeline already tolerates) and the buyout-cohort aggregate
(WB serves it catalogue-wide with no SKU filter, so a DB-free client cannot know
which SKUs to answer for — «Процент выкупа» simply stays blank locally).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import TracebackType
from typing import Self

from src.core.config import Settings
from src.integrations.wildberries.clients.advertising import WBAdvertisingClient
from src.integrations.wildberries.clients.analytics import WBAnalyticsClient
from src.integrations.wildberries.clients.card import WBCardClient
from src.integrations.wildberries.clients.marketplace import WBMarketplaceClient
from src.integrations.wildberries.clients.prices import WBPricesClient
from src.integrations.wildberries.clients.statistics import WBStatisticsClient
from src.integrations.wildberries.schemas import (
    WBAdvCampaignStats,
    WBAdvertV2,
    WBCampaign,
    WBCardPrice,
    WBCardProduct,
    WBCardSizePrice,
    WBFbsStockRow,
    WBFbsWarehouse,
    WBFunnelAggregateRow,
    WBFunnelHistoryDay,
    WBFunnelHistoryProduct,
    WBFunnelHistoryRow,
    WBNormQueryItem,
    WBOrderPrice,
    WBPriceGood,
    WBPriceSize,
    WBSaleRecord,
    WBStockRow,
)

# --------------------------------------------------------------------------- #
# Deterministic pseudo-values
# --------------------------------------------------------------------------- #

#: 32-bit mask keeping the FNV mix in range without pulling in a hash lib.
_MASK32 = 0xFFFFFFFF


def _seed(*parts: int) -> int:
    """A stable 32-bit value derived from the given ints (FNV-1a).

    Pure and clock-free: the same inputs always yield the same number, so a
    SKU's synthetic series is reproducible across refreshes and processes.
    """
    h = 2166136261
    for part in parts:
        h = ((h ^ (part & _MASK32)) * 16777619) & _MASK32
    return h


def _seller_price(nm_id: int) -> float:
    """A stable seller (discounted) price in rubles for a SKU: 500-4950 rub."""
    return float(500 + (_seed(nm_id, 7) % 90) * 50)


def _days(date_from: date, date_to: date) -> list[date]:
    """Every calendar day in the inclusive ``[date_from, date_to]`` window."""
    if date_to < date_from:
        return []
    span = (date_to - date_from).days
    return [date_from + timedelta(days=offset) for offset in range(span + 1)]


def _funnel_day(nm_id: int, day: date, price: float) -> WBFunnelHistoryDay:
    """One deterministic day of funnel metrics for a SKU (a plausible funnel)."""
    base = _seed(nm_id, day.toordinal())
    open_count = 40 + base % 400
    cart_count = round(open_count * (0.20 + (base % 30) / 100))
    order_count = round(cart_count * (0.30 + (base % 20) / 100))
    buyout_count = round(order_count * 0.85)
    cart_conversion = round(cart_count / open_count * 100, 1) if open_count else 0.0
    order_conversion = round(order_count / cart_count * 100, 1) if cart_count else 0.0
    return WBFunnelHistoryDay(
        stat_date=day,
        open_count=open_count,
        cart_count=cart_count,
        order_count=order_count,
        order_sum=round(order_count * price, 2),
        buyout_count=buyout_count,
        buyout_sum=round(buyout_count * price, 2),
        add_to_wishlist=base % 15,
        cart_conversion=cart_conversion,
        order_conversion=order_conversion,
        buyout_conversion=85.0,
    )


# Synthetic warehouses stock is spread across — labels only, purely cosmetic.
_WAREHOUSES: tuple[tuple[str, str], ...] = (
    ("Коледино", "Центральный"),
    ("Электросталь", "Центральный"),
    ("Казань", "Приволжский"),
)


def _stock_rows(nm_id: int, size_ids: list[int]) -> list[WBStockRow]:
    """Per-warehouse, per-size stock rows for a SKU.

    ``size_ids`` are the SKU's REAL ``chrt_id``s, read from the catalogue by the
    harvest and passed down through the factory. They matter because a stock row
    carries no size label of its own: the detail view resolves one by joining
    ``chrt_id`` back to ``product_size``. Inventing an id (as this did) leaves
    every row unlabelled, and the panel falls back to printing the bare
    characteristic id — which is not a bug in the panel, but it is a local-only
    difference from production, and one that reads as one.

    Falls back to derived ids for a SKU the catalogue has never seen (a brand
    new account's first harvest, before its cards land in the same transaction).
    Those rows stay unlabelled — correctly so, since there is no size to name.

    A size is stocked in roughly two thirds of the warehouses, so the grid has
    the holes real stock has instead of being uniformly full.
    """
    rows: list[WBStockRow] = []
    chrt_ids = size_ids or [nm_id * 100 + index for index in range(len(_WAREHOUSES))]

    for index, (warehouse, region) in enumerate(_WAREHOUSES):
        for chrt_id in chrt_ids:
            quantity = _seed(nm_id, index, chrt_id, 11) % 120
            if quantity % 3 == 0:
                continue
            rows.append(
                WBStockRow(
                    nm_id=nm_id,
                    chrt_id=chrt_id,
                    warehouse_name=warehouse,
                    region_name=region,
                    quantity=quantity,
                    in_way_to_client=quantity // 10,
                    in_way_from_client=quantity // 25,
                )
            )
    return rows


# --------------------------------------------------------------------------- #
# Async-context plumbing shared by every synthetic client
# --------------------------------------------------------------------------- #


class _SyntheticWBClient:
    """Mixin giving the synthetic clients an inert async-context lifecycle.

    Placed FIRST in each subclass's bases so its no-op ``__init__`` (which never
    opens an ``httpx.AsyncClient``) and no-op teardown win over the real client's
    — construction and close are free, and no socket is ever created.
    """

    def __init__(self, settings: Settings, *, token: str = "") -> None:
        """Accept the real clients' constructor shape and keep nothing live."""
        self._settings = settings

    async def __aenter__(self) -> Self:
        """Enter the async context, returning the live (inert) client."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Nothing to close — no connection was ever opened."""

    async def aclose(self) -> None:
        """No-op close for symmetry with the real client."""


# --------------------------------------------------------------------------- #
# Synthetic surface clients
# --------------------------------------------------------------------------- #


class SyntheticAnalyticsClient(_SyntheticWBClient, WBAnalyticsClient):
    """Funnel history + stocks, synthesised; the cohort aggregate stays empty."""

    def __init__(
        self,
        settings: Settings,
        *,
        token: str = "",
        size_ids_by_nm: dict[int, list[int]] | None = None,
    ) -> None:
        """Remember each SKU's real size ids, so synthetic stock can use them.

        The real ``fetch_warehouse_stocks`` gets the sizes from WB inside the
        response; a DB-free synthetic client cannot, so the harvest reads them
        from the catalogue and the factory passes them in. The real client
        ignores the argument entirely.
        """
        super().__init__(settings, token=token)
        self._size_ids_by_nm = size_ids_by_nm or {}

    async def fetch_sales_funnel(
        self, *, nm_ids: list[int], date_from: date, date_to: date
    ) -> list[WBFunnelHistoryRow]:
        """One product node per SKU, each with a deterministic daily history."""
        window = _days(date_from, date_to)
        return [
            WBFunnelHistoryRow(
                product=WBFunnelHistoryProduct(nm_id=nm_id),
                history=[_funnel_day(nm_id, day, _seller_price(nm_id)) for day in window],
            )
            for nm_id in nm_ids
        ]

    async def fetch_warehouse_stocks(self, *, nm_ids: list[int]) -> list[WBStockRow]:
        """A flat list of per-warehouse, per-size stock snapshots for the SKUs."""
        return [
            row
            for nm_id in nm_ids
            for row in _stock_rows(nm_id, self._size_ids_by_nm.get(nm_id, []))
        ]

    async def fetch_funnel_cohort_day(self, *, day: date) -> list[WBFunnelAggregateRow]:
        """No synthetic cohorts: the real endpoint is catalogue-wide and takes
        no SKU filter, so a DB-free client has no basis to answer. «Процент
        выкупа» therefore stays blank under fake harvesting."""
        return []


class SyntheticAdvertisingClient(_SyntheticWBClient, WBAdvertisingClient):
    """No synthetic advertising — an account with no campaigns is a valid state."""

    async def fetch_full_stats(
        self, *, campaign_ids: list[int], date_from: date, date_to: date
    ) -> list[WBAdvCampaignStats]:
        """No campaigns, so no full stats."""
        return []

    async def list_campaigns(self) -> list[WBCampaign]:
        """No advertising campaigns locally."""
        return []

    async def list_adverts(self) -> list[WBAdvertV2]:
        """No adverts locally."""
        return []

    async def fetch_search_zone_stats(
        self, *, pairs: list[tuple[int, int]], date_from: date, date_to: date
    ) -> list[WBNormQueryItem]:
        """No search-zone traffic without campaigns."""
        return []


class SyntheticPricesClient(_SyntheticWBClient, WBPricesClient):
    """Seller prices for a fixed set of SKUs (the harvested ones)."""

    def __init__(self, settings: Settings, *, token: str = "", nm_ids: list[int]) -> None:
        """Remember which SKUs to price.

        The real ``fetch_prices`` takes no arguments (WB returns the whole
        account), so the synthetic client is told the harvested SKUs up front —
        the factory passes them; the real client ignores them.
        """
        super().__init__(settings, token=token)
        self._nm_ids = nm_ids

    async def fetch_prices(self) -> list[WBPriceGood]:
        """One priced goods record per known SKU (all sizes share the price)."""
        goods: list[WBPriceGood] = []
        for nm_id in self._nm_ids:
            price = _seller_price(nm_id)
            goods.append(
                WBPriceGood(
                    nm_id=nm_id,
                    discount=_seed(nm_id, 3) % 40,
                    sizes=[WBPriceSize(price=price * 1.4, discounted_price=price)],
                )
            )
        return goods


class SyntheticStatisticsClient(_SyntheticWBClient, WBStatisticsClient):
    """The account-wide sale/return feed, empty (the buttons skip it anyway)."""

    async def fetch_sales(self, *, changed_since: date | datetime) -> list[WBSaleRecord]:
        """No synthetic sale-date records."""
        return []

    async def fetch_order_prices(self, *, changed_since: date | datetime) -> list[WBOrderPrice]:
        """No synthetic ordered lines, so local runs price from the card feed."""
        return []


class SyntheticMarketplaceClient(_SyntheticWBClient, WBMarketplaceClient):
    """Several FBS warehouses, each holding a deterministic slice of the sizes."""

    async def fetch_warehouses(self) -> list[WBFbsWarehouse]:
        """The configured warehouses plus one unnamed in config.

        More than one, and one WITHOUT a configured label, so a local run
        exercises the shape prod actually has: several warehouses read in turn,
        and a newly discovered one labelled from WB's own name.
        """
        configured = [
            WBFbsWarehouse(
                id=warehouse_id,
                name=label,
                office_id=236,
                cargo_type=1,
                delivery_type=1,
            )
            for warehouse_id, label in sorted(self._settings.wb_fbs_warehouse_labels.items())
        ]
        return [
            *configured,
            WBFbsWarehouse(
                id=3300771,
                name="Иван  - Тула НЕ УДАЛЯТЬ!!!",
                office_id=507,
                cargo_type=1,
                delivery_type=1,
            ),
        ]

    async def fetch_stocks(self, *, warehouse_id: int, skus: list[str]) -> list[WBFbsStockRow]:
        """Stock for roughly two thirds of the asked-for barcodes.

        The holes are the point: the real endpoint omits barcodes it does not
        know at that warehouse, so a synthetic run that answered every barcode
        would hide the absent-is-not-zero case the ingestion has to handle.
        """
        rows: list[WBFbsStockRow] = []
        for sku in skus:
            seed = _seed(warehouse_id, *(ord(ch) for ch in sku[-6:]))
            if seed % 3 == 0:
                continue
            rows.append(WBFbsStockRow(sku=sku, chrt_id=0, amount=seed % 200))
        return rows


class SyntheticCardClient(_SyntheticWBClient, WBCardClient):
    """Storefront customer prices, so «СПП» has a value below the seller price."""

    async def fetch_customer_prices(self, nm_ids: list[int]) -> list[WBCardProduct]:
        """A storefront node per SKU, priced ~10% under the seller price (in
        kopecks, as the real endpoint returns), giving a positive СПП."""
        products: list[WBCardProduct] = []
        for nm_id in nm_ids:
            kopecks = round(_seller_price(nm_id) * 0.9 * 100)
            price = WBCardPrice(basic=kopecks + 5000, product=kopecks, total=kopecks)
            products.append(WBCardProduct(nm_id=nm_id, sizes=[WBCardSizePrice(price=price)]))
        return products
