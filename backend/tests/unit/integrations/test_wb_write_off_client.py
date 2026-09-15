"""Unit tests for ``WBAdvertisingClient.fetch_write_offs`` (``/adv/v1/upd``).

The endpoint is small but three of its properties are load-bearing, and all
three are asserted here rather than trusted: WB caps the interval at one month,
it answers ``null`` (not ``[]``) for an empty window, and it serves rows whose
``currency`` differs inside a single response.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.advertising import WBAdvertisingClient


class _StubClient(WBAdvertisingClient):
    """A client whose transport is a scripted list of payloads."""

    def __init__(self, payloads: list[Any]) -> None:
        self._payloads = payloads
        self.calls: list[dict[str, str]] = []

    async def _request(  # type: ignore[override]
        self, method: str, path: str, *, params: dict[str, Any] | None = None, **_: Any
    ) -> Any:
        self.calls.append(dict(params or {}))
        return self._payloads[len(self.calls) - 1]


async def test_a_window_wider_than_a_month_is_walked_in_steps() -> None:
    """WB rejects a wider interval outright, so the client must split it.

    Asserted on the REQUESTED windows, not just the row count: the steps have to
    tile the range with no gap and no overlap, or a day's charges are lost or
    counted twice.
    """
    client = _StubClient([[], [], []])

    await client.fetch_write_offs(date_from=date(2026, 7, 1), date_to=date(2026, 9, 15))

    assert client.calls == [
        {"from": "2026-07-01", "to": "2026-07-30"},
        {"from": "2026-07-31", "to": "2026-08-29"},
        {"from": "2026-08-30", "to": "2026-09-15"},
    ]


async def test_a_window_inside_the_cap_is_one_request() -> None:
    """The common case — the nightly harvest's seven days — costs one call."""
    client = _StubClient([[]])

    await client.fetch_write_offs(date_from=date(2026, 9, 9), date_to=date(2026, 9, 15))

    assert client.calls == [{"from": "2026-09-09", "to": "2026-09-15"}]


async def test_a_null_payload_is_an_empty_window_not_a_failure() -> None:
    """WB answers ``null`` for a window it charged nothing in."""
    client = _StubClient([None])

    assert (
        await client.fetch_write_offs(date_from=date(2026, 9, 9), date_to=date(2026, 9, 15)) == []
    )


async def test_a_non_list_payload_raises_instead_of_reading_as_no_bonuses() -> None:
    """A silent contract change must not be persisted as «бонусов не было».

    Defaulting to empty here would sweep a good window and rewrite it with
    nothing — a flattering number that no assertion downstream would catch.
    """
    client = _StubClient([{"error": "Invalid Params"}])

    with pytest.raises(IntegrationError, match="adv/v1/upd"):
        await client.fetch_write_offs(date_from=date(2026, 9, 9), date_to=date(2026, 9, 15))


async def test_the_rows_keep_their_own_currency_and_zero_updnum() -> None:
    """Both traps survive parsing: neither is normalised away."""
    client = _StubClient(
        [
            [
                {
                    "updTime": "2026-09-05T18:00:00.002269+03:00",
                    "updSum": 17500,
                    "updNum": 0,
                    "advertId": 97455888,
                    "advertType": 9,
                    "advertStatus": 9,
                    "campName": "M-TRX01-CHK /995716075 / РУЧНАЯ ПОИСК",
                    "paymentType": "Кэшбэк",
                    "currency": "KGS",
                },
                {
                    "updTime": "2026-09-05T19:00:00+03:00",
                    "updSum": 78,
                    "updNum": 922370716,
                    "advertId": 91570710,
                    "paymentType": "Баланс",
                    "currency": "RUB",
                },
            ]
        ]
    )

    rows = await client.fetch_write_offs(date_from=date(2026, 9, 1), date_to=date(2026, 9, 15))

    assert [r.payment_type for r in rows] == ["Кэшбэк", "Баланс"]
    assert [r.currency for r in rows] == ["KGS", "RUB"]
    assert rows[0].upd_sum == Decimal("17500")
    assert rows[0].campaign_id == 97455888
