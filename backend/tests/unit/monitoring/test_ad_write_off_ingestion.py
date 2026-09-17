"""Unit tests for the advertising write-off ledger — who funded the ads.

The payload these tests are built from is the live 2026-08..09 shape of the
`Демо` workspace, and every case here is a way the feed has already been
read wrong or could plausibly be:

* ``updNum`` is ``0`` on every cashback row, so it identifies nothing. A first
  pass deduped on it and reported 500 KGS of bonuses where there were 169 000;
* ``currency`` varies inside a single window (RUB and KGS on one account), so
  amounts must never be summed across it;
* ``updTime`` is a charge stamp, not a display day, and it is the ONLY date the
  feed carries;
* a sweep before re-insert must not reach another account's campaigns.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from src.integrations.wildberries.schemas import WBAdvWriteOff
from src.modules.monitoring.services import IngestionService

WINDOW = (date(2026, 9, 1), date(2026, 9, 15))


class _CapturingWriteOffRepo:
    """Stands in for AdvertisingWriteOffRepository."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.swept: list[dict[str, Any]] = []

    async def upsert_many(self, rows: list[dict[str, Any]]) -> int:
        self.rows = rows
        return len(rows)

    async def delete_window_for_campaigns(
        self, *, date_from: date, date_to: date, campaign_ids: Any
    ) -> int:
        self.swept.append(
            {"date_from": date_from, "date_to": date_to, "campaign_ids": list(campaign_ids)}
        )
        return 0


def _service(write_off_repo: Any) -> IngestionService:
    """Build an IngestionService with only the write-off repo wired."""
    return IngestionService(
        funnel_repo=None,  # type: ignore[arg-type]
        advertising_repo=None,  # type: ignore[arg-type]
        stock_repo=None,  # type: ignore[arg-type]
        campaign_repo=None,  # type: ignore[arg-type]
        product_card_repo=None,  # type: ignore[arg-type]
        product_size_repo=None,  # type: ignore[arg-type]
        advertising_search_repo=None,  # type: ignore[arg-type]
        advertising_cluster_repo=None,  # type: ignore[arg-type]
        advertising_write_off_repo=write_off_repo,
        price_repo=None,  # type: ignore[arg-type]
        sale_repo=None,  # type: ignore[arg-type]
        order_repo=None,  # type: ignore[arg-type]
    )


def _write_off(
    *,
    when: str = "2026-09-05T18:00:00.002269+03:00",
    amount: str = "17500",
    campaign_id: int = 97455888,
    payment_type: str = "Кэшбэк",
    upd_num: int = 0,
    currency: str = "KGS",
) -> WBAdvWriteOff:
    """One ledger row in WB's own wire shape."""
    return WBAdvWriteOff.model_validate(
        {
            "updTime": when,
            "updSum": Decimal(amount),
            "updNum": upd_num,
            "advertId": campaign_id,
            "paymentType": payment_type,
            "currency": currency,
        }
    )


def _by_key(rows: list[dict[str, Any]]) -> dict[tuple[Any, ...], dict[str, Any]]:
    """Index persisted buckets by their composite key."""
    return {(r["stat_date"], r["campaign_id"], r["payment_type"], r["currency"]): r for r in rows}


async def test_cashback_rows_are_not_collapsed_by_their_zero_updnum() -> None:
    """Every cashback row carries ``updNum = 0``; it must key nothing.

    This is the bug that produced 500 KGS where the month held 169 000 — the
    regression the whole table's grain is chosen to prevent.
    """
    repo = _CapturingWriteOffRepo()
    rows = [
        _write_off(when="2026-09-05T18:00:00+03:00", amount="17500"),
        _write_off(when="2026-09-05T22:45:00+03:00", amount="2000"),
        _write_off(when="2026-09-05T23:10:00+03:00", amount="1500"),
    ]

    await _service(repo).ingest_write_offs(rows, window=WINDOW)

    bucket = _by_key(repo.rows)[(date(2026, 9, 5), 97455888, "Кэшбэк", "KGS")]
    assert bucket["amount"] == Decimal("21000")
    assert bucket["write_offs"] == 3


async def test_currencies_are_kept_in_separate_buckets() -> None:
    """WB books RUB and KGS in one window; adding them adds unlike units."""
    repo = _CapturingWriteOffRepo()
    rows = [
        _write_off(payment_type="Баланс", amount="1000", currency="KGS"),
        _write_off(payment_type="Баланс", amount="1000", currency="RUB"),
    ]

    await _service(repo).ingest_write_offs(rows, window=WINDOW)

    buckets = _by_key(repo.rows)
    assert buckets[(date(2026, 9, 5), 97455888, "Баланс", "KGS")]["amount"] == Decimal("1000")
    assert buckets[(date(2026, 9, 5), 97455888, "Баланс", "RUB")]["amount"] == Decimal("1000")


async def test_funding_sources_are_kept_apart_within_one_day() -> None:
    """The split between the seller's money and WB's is the whole point."""
    repo = _CapturingWriteOffRepo()
    rows = [
        _write_off(payment_type="Баланс", amount="19402"),
        _write_off(payment_type="Кэшбэк", amount="17500"),
    ]

    await _service(repo).ingest_write_offs(rows, window=WINDOW)

    buckets = _by_key(repo.rows)
    assert buckets[(date(2026, 9, 5), 97455888, "Баланс", "KGS")]["amount"] == Decimal("19402")
    assert buckets[(date(2026, 9, 5), 97455888, "Кэшбэк", "KGS")]["amount"] == Decimal("17500")


async def test_the_charge_is_dated_by_its_moscow_day() -> None:
    """A charge stamped just past midnight belongs to the day WB booked it.

    WB serves ``+03:00`` today, but the rest of the monitoring series is Moscow
    days by construction, so the conversion is explicit rather than trusted.
    """
    repo = _CapturingWriteOffRepo()
    rows = [_write_off(when="2026-09-05T23:59:59+03:00", amount="78")]

    await _service(repo).ingest_write_offs(rows, window=WINDOW)

    assert repo.rows[0]["stat_date"] == date(2026, 9, 5)


async def test_a_charge_outside_the_asked_window_is_not_persisted() -> None:
    """WB returns boundary rows past the window it was asked for.

    Such a row would survive the next pass's sweep (that pass sweeps ITS window)
    and be counted twice.
    """
    repo = _CapturingWriteOffRepo()
    rows = [
        _write_off(when="2026-09-05T12:00:00+03:00", amount="100"),
        _write_off(when="2026-09-16T01:09:21+03:00", amount="999"),
    ]

    await _service(repo).ingest_write_offs(rows, window=WINDOW)

    assert [r["stat_date"] for r in repo.rows] == [date(2026, 9, 5)]


async def test_the_sweep_is_scoped_to_the_campaigns_in_the_payload() -> None:
    """The feed is per advertising token: a bare window sweep crosses accounts."""
    repo = _CapturingWriteOffRepo()
    rows = [
        _write_off(campaign_id=97455888, amount="100"),
        _write_off(campaign_id=97455887, amount="200"),
    ]

    await _service(repo).ingest_write_offs(rows, window=WINDOW)

    assert repo.swept == [
        {
            "date_from": WINDOW[0],
            "date_to": WINDOW[1],
            "campaign_ids": [97455887, 97455888],
        }
    ]


async def test_an_empty_ledger_sweeps_nothing() -> None:
    """No payload means no campaigns to rewrite — and nothing to delete.

    Sweeping on an empty answer would erase a good window whenever WB happened
    to return nothing.
    """
    repo = _CapturingWriteOffRepo()

    await _service(repo).ingest_write_offs([], window=WINDOW)

    assert repo.swept == []
    assert repo.rows == []
