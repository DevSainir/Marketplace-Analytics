"""Walks over feeds WB serves a date window at a time.

Each yields one batch per window, so a walk cut short keeps the windows it
finished — see :class:`~.common.CaptureBatch` for why the watermark may only
move on a window boundary.

All four cap a request at 31 days and answer a wider one with HTTP 400, so a
walk over history is a sequence of windows. Two of them (the tariff calendars)
are not windows at all but single days, because WB serves the calendar as it
stands on the day asked for and never as it stood — the history is ours to
accumulate, one day per request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, timedelta

from src.integrations.wildberries.clients.reference import WBReferenceClient
from src.modules.guide.services.fetch.common import (
    CaptureBatch,
    CaptureWindow,
    as_rows,
    parse_day,
    windows,
)

#: WB's window cap on every one of these reports, measured: a wider request
#: comes back ``400 {"detail": "difference between dateFrom and dateTo should
#: be less or equal 31 days"}``.
_WINDOW_DAYS = 31

#: The acceptance report is asynchronous — create, poll, download — so a window
#: costs up to two minutes of polling rather than one request. Fewer windows per
#: run than the plain reports, so one run cannot sit on a worker slot.
_ACCEPTANCE_MAX_WINDOWS = 4

#: The tariff calendars stop answering about seventy days back (measured:
#: 2026-07-04 returns warehouses, 2026-06-29 returns an empty list), so there is
#: no point walking a first run to the history floor.
_TARIFF_REACHABLE_DAYS = 69
#: Days one run will ask the calendar for. A month of catch-up plus slack.
_TARIFF_MAX_DAYS_PER_RUN = 40


async def _walk_report(
    client: WBReferenceClient,
    window: CaptureWindow,
    *,
    path: str,
    envelope: str,
    date_field: str | None,
    key_fields: tuple[str, ...],
    key_with_window: bool = False,
    limit: int | None = None,
) -> AsyncIterator[CaptureBatch]:
    """Walk one windowed report forward, oldest window first, a window at a time.

    Args:
        client: Reference client on the report's host.
        window: Where the last run stopped and this run's window budget.
        path: WB path.
        envelope: Key the rows sit under in the response object.
        date_field: Row field naming the day it is about.
        key_fields: Row fields that together identify a row. Joined with ``|``;
            WB gives none of these reports an id of its own, so identity has to
            be built from the fields that make a row unique — get this wrong and
            a re-read overwrites rows instead of adding them.
        key_with_window: Put the window's start in the key too. Needed when the
            report is an AGGREGATE over the window and its rows carry no date of
            their own: the same SKU sells in the same city every month, so
            without the window every walk would overwrite the previous one's
            rows instead of adding to them.
        limit: Window budget override.

    Yields:
        One batch per window, each carrying the last day it covers. A run cut
        short by an error therefore keeps every window before the failed one,
        instead of throwing the whole walk away and re-reading it next month.
    """
    start = window.resume_from()
    end = window.yesterday
    if start > end:
        return

    budget = window.max_windows if limit is None else min(window.max_windows, limit)
    for begin, stop in windows(start, end, span_days=_WINDOW_DAYS, limit=budget):
        payload = await client.get(
            path, {"dateFrom": begin.isoformat(), "dateTo": stop.isoformat()}
        )
        report = payload.get(envelope) if isinstance(payload, dict) else None
        window_start = begin

        def key_of(item: dict[str, object], _start: date = window_start) -> str:
            body = "|".join(str(item.get(field, "")) for field in key_fields)
            return f"{_start.isoformat()}|{body}" if key_with_window else body

        yield CaptureBatch(
            rows=as_rows(
                report,
                key_of=key_of,
                day_of=(
                    (lambda item: parse_day(item.get(date_field)))
                    if date_field
                    else (lambda item, _start=window_start: _start)
                ),
            ),
            captured_through=stop,
        )


async def fetch_region_sale(
    client: WBReferenceClient, window: CaptureWindow
) -> AsyncIterator[CaptureBatch]:
    """Walk the "Sales by region" report, 31 days at a time.

    WB gives these rows no identity and no date of their own — the report is an
    aggregate over whatever window was asked for — so the key is that window
    plus the grain: SKU, country, region, city, article.
    """
    async for batch in _walk_report(
        client,
        window,
        path="/api/v1/analytics/region-sale",
        envelope="report",
        date_field=None,
        key_fields=("nmID", "countryName", "regionName", "cityName", "sa"),
        key_with_window=True,
    ):
        yield batch


async def fetch_goods_return(
    client: WBReferenceClient, window: CaptureWindow
) -> AsyncIterator[CaptureBatch]:
    """Walk the "Product returns" report, 31 days at a time."""
    async for batch in _walk_report(
        client,
        window,
        path="/api/v1/analytics/goods-return",
        envelope="report",
        date_field="orderDt",
        key_fields=("srid", "barcode", "orderDt", "nmId"),
    ):
        yield batch


async def fetch_acceptance_report(
    client: WBReferenceClient, window: CaptureWindow
) -> AsyncIterator[CaptureBatch]:
    """Walk the "Paid acceptance" report, 31 days at a time through the async report flow.

    An empty window answers ``204`` — decoded as ``None`` — which is not an
    error and not a reason to stop: a seller simply shipped nothing that month.
    """
    start = window.resume_from()
    end = window.yesterday
    if start > end:
        return
    budget = min(window.max_windows, _ACCEPTANCE_MAX_WINDOWS)
    for begin, stop in windows(start, end, span_days=_WINDOW_DAYS, limit=budget):
        payload = await client.run_report(
            "/api/v1/acceptance_report",
            {"dateFrom": begin.isoformat(), "dateTo": stop.isoformat()},
        )
        yield CaptureBatch(
            rows=as_rows(
                payload,
                key_of=lambda item: (
                    f"{item.get('incomeId', '')}|{item.get('nmID', '')}"
                    f"|{item.get('shkCreateDate', '')}"
                ),
                day_of=lambda item: parse_day(item.get("shkCreateDate")),
            ),
            captured_through=stop,
        )


async def _walk_tariff_calendar(
    client: WBReferenceClient,
    window: CaptureWindow,
    *,
    path: str,
    prefix: str,
) -> AsyncIterator[CaptureBatch]:
    """Snapshot one tariff calendar for each day still reachable.

    One request per day, because WB answers with the calendar valid on the day
    asked for — there is no window parameter and no history endpoint. A day
    nobody asked on inside the reachable ~70 days is a day whose rates are gone
    for good, which is the whole reason this is captured at all.
    """
    reachable_from = window.yesterday - timedelta(days=_TARIFF_REACHABLE_DAYS)
    start = max(window.resume_from(), reachable_from)
    end = window.yesterday
    if start > end:
        return
    day = start
    asked = 0
    while day <= end and asked < _TARIFF_MAX_DAYS_PER_RUN:
        payload = await client.get(path, {"date": day.isoformat()})
        response = payload.get("response") if isinstance(payload, dict) else None
        data = response.get("data") if isinstance(response, dict) else None
        warehouses = data.get("warehouseList") if isinstance(data, dict) else None
        on_day = day

        def key_of(item: dict[str, object], _day: date = on_day) -> str:
            return f"{prefix}|{_day.isoformat()}|{item.get('warehouseName', '')}"

        yield CaptureBatch(
            rows=as_rows(
                warehouses,
                key_of=key_of,
                day_of=lambda item, _day=on_day: _day,
            ),
            captured_through=day,
        )
        day += timedelta(days=1)
        asked += 1


async def fetch_tariffs_pallet(
    client: WBReferenceClient, window: CaptureWindow
) -> AsyncIterator[CaptureBatch]:
    """Snapshot the pallet tariff calendar, one day per request."""
    async for batch in _walk_tariff_calendar(
        client, window, path="/api/v1/tariffs/pallet", prefix="pallet"
    ):
        yield batch


async def fetch_tariffs_return(
    client: WBReferenceClient, window: CaptureWindow
) -> AsyncIterator[CaptureBatch]:
    """Snapshot the return tariff calendar, one day per request."""
    async for batch in _walk_tariff_calendar(
        client, window, path="/api/v1/tariffs/return", prefix="return"
    ):
        yield batch


__all__ = [
    "fetch_acceptance_report",
    "fetch_goods_return",
    "fetch_region_sale",
    "fetch_tariffs_pallet",
    "fetch_tariffs_return",
]
