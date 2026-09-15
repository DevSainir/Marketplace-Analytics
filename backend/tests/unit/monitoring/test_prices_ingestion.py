"""Unit tests for price parsing + the price-snapshot ingestion join.

Covers the raw-shape extraction (seller ``discountedPrice``, customer ``product``
in kopecks) and the join into one snapshot row per SKU, including the
one-source-only and both-missing cases.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.integrations.wildberries.schemas import WBCardProduct, WBPriceGood
from src.modules.monitoring.services.ingestion import IngestionService

DAY = date(2026, 7, 1)


# --------------------------------------------------------------------------- #
# Raw shape parsing
# --------------------------------------------------------------------------- #
def test_price_good_takes_first_positive_discounted_price() -> None:
    """Seller price = first size's positive ``discountedPrice`` (rubles)."""
    good = WBPriceGood.model_validate(
        {
            "nmID": 111,
            "discount": 10,
            "sizes": [
                {"price": 600.0, "discountedPrice": 0.0},
                {"price": 600.0, "discountedPrice": 540.0},
            ],
        }
    )

    assert good.nm_id == 111
    assert good.seller_price == 540.0


def test_price_good_seller_price_none_when_all_zero() -> None:
    """No positive discounted price -> ``None`` (unpriced)."""
    good = WBPriceGood.model_validate({"nmID": 5, "sizes": [{"discountedPrice": 0.0}]})

    assert good.seller_price is None


def test_card_product_customer_price_is_kopecks_over_100() -> None:
    """Customer price = ``product`` kopecks / 100 (falls back to ``total``)."""
    product = WBCardProduct.model_validate(
        {"id": 111, "sizes": [{"price": {"basic": 60000, "product": 35000, "total": 35000}}]}
    )

    assert product.nm_id == 111
    assert product.customer_price == 350.0


def test_card_product_falls_back_to_total_when_no_product() -> None:
    """When ``product`` is 0, the shown price falls back to ``total``."""
    product = WBCardProduct.model_validate(
        {"id": 9, "sizes": [{"price": {"basic": 50000, "product": 0, "total": 42000}}]}
    )

    assert product.customer_price == 420.0


# --------------------------------------------------------------------------- #
# Ingestion join
# --------------------------------------------------------------------------- #
class _CapturingPriceRepo:
    """A stub price repo capturing the rows an ingest would upsert."""

    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        """Record the rows and report the count, mirroring the real repo."""
        self.rows = rows
        return len(rows)


def _service(price_repo: Any) -> IngestionService:
    """Build an IngestionService with only the price repo wired (others unused)."""
    return IngestionService(
        funnel_repo=None,  # type: ignore[arg-type]
        advertising_repo=None,  # type: ignore[arg-type]
        stock_repo=None,  # type: ignore[arg-type]
        campaign_repo=None,  # type: ignore[arg-type]
        product_card_repo=None,  # type: ignore[arg-type]
        product_size_repo=None,  # type: ignore[arg-type]
        advertising_search_repo=None,  # type: ignore[arg-type]
        advertising_cluster_repo=None,  # type: ignore[arg-type]
        advertising_write_off_repo=None,  # type: ignore[arg-type]
        price_repo=price_repo,
        sale_repo=None,  # type: ignore[arg-type]
    )


async def test_ingest_prices_joins_seller_and_customer_by_sku() -> None:
    """Seller + customer prices join into one snapshot row per SKU."""
    repo = _CapturingPriceRepo()
    service = _service(repo)
    goods = [
        WBPriceGood.model_validate({"nmID": 1, "sizes": [{"discountedPrice": 500.0}]}),
        WBPriceGood.model_validate({"nmID": 2, "sizes": [{"discountedPrice": 700.0}]}),
    ]
    customer = [
        WBCardProduct.model_validate({"id": 1, "sizes": [{"price": {"product": 35000}}]}),
        # SKU 3 has only a customer price (no seller record).
        WBCardProduct.model_validate({"id": 3, "sizes": [{"price": {"product": 12300}}]}),
    ]

    count = await service.ingest_prices(goods, customer, snapshot_date=DAY)

    by_sku = {row["nm_id"]: row for row in repo.rows}
    assert count == 3
    assert by_sku[1] == {
        "stat_date": DAY,
        "nm_id": 1,
        "seller_price": 500.0,
        "customer_price": 350.0,
    }
    # SKU 2: seller only (no storefront row) -> customer None.
    assert by_sku[2]["seller_price"] == 700.0
    assert by_sku[2]["customer_price"] is None
    # SKU 3: customer only (no seller record) -> seller None.
    assert by_sku[3]["seller_price"] is None
    assert by_sku[3]["customer_price"] == 123.0


async def test_ingest_prices_scopes_to_harvested_nm_ids() -> None:
    """With ``nm_ids`` set, only those SKUs are snapshotted (single-SKU refresh).

    The seller feed is account-wide but a scoped refresh must not stamp the other
    SKUs' rows (their customer price would be wiped to NULL).
    """
    repo = _CapturingPriceRepo()
    service = _service(repo)
    goods = [
        WBPriceGood.model_validate({"nmID": 1, "sizes": [{"discountedPrice": 500.0}]}),
        WBPriceGood.model_validate({"nmID": 2, "sizes": [{"discountedPrice": 700.0}]}),
    ]
    customer = [WBCardProduct.model_validate({"id": 1, "sizes": [{"price": {"product": 35000}}]})]

    count = await service.ingest_prices(goods, customer, snapshot_date=DAY, nm_ids=[1])

    assert count == 1
    assert [row["nm_id"] for row in repo.rows] == [1]
    assert repo.rows[0]["customer_price"] == 350.0


async def test_ingest_prices_skips_fully_empty_skus() -> None:
    """A SKU with neither a seller nor a customer price yields no row."""
    repo = _CapturingPriceRepo()
    service = _service(repo)
    goods = [WBPriceGood.model_validate({"nmID": 8, "sizes": [{"discountedPrice": 0.0}]})]
    customer: list[WBCardProduct] = []

    count = await service.ingest_prices(goods, customer, snapshot_date=DAY)

    assert count == 0
    assert repo.rows == []
