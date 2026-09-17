"""Walks over feeds WB serves as a stream or a page, not as a date window.

Three shapes live here: a cursor stream (orders), a snapshot whose whole content
is the answer (claims), and take/skip paging (reviews, questions, documents).
Each yields batches and the resume point each batch makes safe; none of them
touches the database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from src.integrations.wildberries.clients.reference import WBReferenceClient
from src.modules.guide.services.fetch.common import (
    CaptureBatch,
    CaptureWindow,
    as_rows,
    parse_day,
    windows,
)

#: WB caps one ``supplier/orders`` response at 80 000 rows and offers no page
#: parameter: the next page is the same request from the last row's
#: ``lastChangeDate``. A response shorter than this is therefore the last one.
_ORDERS_PAGE_LIMIT = 80000

#: Rows of the orders stream handed over at a time, and therefore the whole
#: feed's memory ceiling: ~5 MB at ~2.5 KB a decoded order.
#:
#: This number replaced the page as the ceiling on 2026-09-17. Before it, a run
#: accumulated every page it walked and handed the lot over at the end — eight
#: pages of 80 000 rows was the documented budget, roughly 1.6 GB of Python
#: against a 768 MiB worker, and the second page of one first run was enough to
#: get the process killed. The page limit above is now only WB's own, used to
#: tell a full response from the last one.
_ORDERS_BATCH = 2000

#: The orders cursor only accepts ``lastChangeDate``, which is not unique, so
#: consecutive pages overlap by however many rows share the boundary second.
#: Rows are keyed by ``srid``, so the overlap upserts onto itself instead of
#: duplicating — and the walk stops if a full page fails to advance the cursor,
#: which would otherwise loop forever.
_ORDERS_PATH = "/api/v1/supplier/orders"


async def fetch_orders(
    client: WBReferenceClient, window: CaptureWindow
) -> AsyncIterator[CaptureBatch]:
    """Walk the orders stream forward from the last ``lastChangeDate`` seen.

    On a first run this starts at the floor WB still serves rather than at the
    module's history floor: the cursor form of this feed refuses anything older
    than about 181 days, and asking for 2024 simply returns the same first row
    as asking for the cliff.

    **The cursor moves only between pages, never inside one.** WB does not order
    a page by ``lastChangeDate``, so the largest value seen after half a page is
    not a point the walk could resume from — rows further down the same page can
    be older, and a resume from that value would step over them. Rows are
    therefore yielded with no cursor as they arrive, and the page's maximum is
    yielded on its own once the page has ended and every row in it is stored.

    Args:
        client: Reference client on the statistics host.
        window: Previous cursor and this run's page budget.

    Yields:
        Batches of order rows, then the new cursor once a page is complete.
    """
    cursor = window.cursor or f"{window.floor.isoformat()}T00:00:00"
    newest = cursor
    for _ in range(max(1, window.max_pages)):
        page_rows = 0
        page_max = ""
        async for chunk in client.stream(
            _ORDERS_PATH, {"dateFrom": cursor, "flag": 0}, batch_size=_ORDERS_BATCH
        ):
            page_rows += len(chunk)
            for item in chunk:
                if isinstance(item, dict):
                    stamp = str(item.get("lastChangeDate") or "")
                    if stamp > page_max:
                        page_max = stamp
            yield CaptureBatch(
                rows=as_rows(
                    chunk,
                    key_of=lambda item: item["srid"],
                    day_of=lambda item: parse_day(item.get("date")),
                )
            )
        if page_max > newest:
            newest = page_max
        # Everything WB served for this cursor is now stored, so the walk may
        # say where it stands.
        yield CaptureBatch(cursor=newest)
        if page_rows < _ORDERS_PAGE_LIMIT:
            return
        if not page_max or page_max <= cursor:
            # A full page that did not advance the cursor: asking again would
            # return the same rows forever. Stop and keep what we have.
            return
        cursor = page_max


async def fetch_claims(
    client: WBReferenceClient, window: CaptureWindow
) -> AsyncIterator[CaptureBatch]:
    """Capture every return claim WB still holds, open and archived.

    There is no cursor and no window: WB keeps fourteen days and serves all of
    it, so each run re-reads the whole thing and upserts. That is also why this
    runs daily — a fortnight is the entire memory of this feed.

    Args:
        client: Reference client on the returns host.
        window: Unused; the feed has no date parameters and no resume point.

    Yields:
        One batch per half — open, then archived.
    """
    for archived in ("true", "false"):
        payload = await client.get(
            "/api/v1/claims",
            {"is_archive": archived, "limit": 200, "offset": 0},
        )
        claims = payload.get("claims") if isinstance(payload, dict) else None
        yield CaptureBatch(
            rows=as_rows(
                claims,
                key_of=lambda item: item["id"],
                day_of=lambda item: parse_day(item.get("dt")),
            )
        )


async def _take_skip(
    client: WBReferenceClient,
    window: CaptureWindow,
    *,
    path: str,
    envelope: str,
    date_field: str,
) -> AsyncIterator[CaptureBatch]:
    """Walk a ``take``/``skip`` feed oldest-first, resuming from the last offset.

    Oldest-first (``order=dateAsc``) rather than newest-first, because the
    offset is only a stable resume point when new rows land at the END of the
    sequence. Newest-first would shift every offset each time a review arrived,
    and the walk would re-read and miss rows in the same pass.

    Each page carries its own new offset, so a run cut short by an error keeps
    every page before the one that failed.
    """
    skip = int(window.cursor) if window.cursor and window.cursor.isdigit() else 0
    take = 1000
    captured = 0
    while captured < window.max_rows:
        payload = await client.get(
            path, {"isAnswered": "true", "take": take, "skip": skip, "order": "dateAsc"}
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        items = data.get(envelope) if isinstance(data, dict) else None
        page = as_rows(
            items,
            key_of=lambda item: item["id"],
            day_of=lambda item: parse_day(item.get(date_field)),
        )
        skip += len(page)
        captured += len(page)
        yield CaptureBatch(rows=page, cursor=str(skip))
        if not isinstance(items, list) or len(items) < take:
            return


async def fetch_feedbacks(
    client: WBReferenceClient, window: CaptureWindow
) -> AsyncIterator[CaptureBatch]:
    """Capture answered reviews, oldest first, resuming from the last offset."""
    async for batch in _take_skip(
        client, window, path="/api/v1/feedbacks", envelope="feedbacks", date_field="createdDate"
    ):
        yield batch


async def fetch_questions(
    client: WBReferenceClient, window: CaptureWindow
) -> AsyncIterator[CaptureBatch]:
    """Capture answered buyer questions, on the same walk as reviews."""
    async for batch in _take_skip(
        client, window, path="/api/v1/questions", envelope="questions", date_field="createdDate"
    ):
        yield batch


async def fetch_documents(
    client: WBReferenceClient, window: CaptureWindow
) -> AsyncIterator[CaptureBatch]:
    """Capture the document index, one bounded window of history per run.

    WB pages this fifty at a time and returns the NEWEST fifty of whatever
    window it is asked for, so paging by offset is not available — the walk is
    by date window instead, oldest first, and ``captured_through`` carries it.
    """
    start = window.resume_from()
    end = window.yesterday
    if start > end:
        return
    for begin, stop in windows(start, end, span_days=31, limit=window.max_windows):
        payload = await client.get(
            "/api/v1/documents/list",
            {"locale": "ru", "beginTime": begin.isoformat(), "endTime": stop.isoformat()},
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        documents = data.get("documents") if isinstance(data, dict) else None
        yield CaptureBatch(
            rows=as_rows(
                documents,
                key_of=_document_key,
                day_of=lambda item: parse_day(item.get("creationTime")),
            ),
            captured_through=stop,
        )


def _document_key(item: dict[str, Any]) -> str:
    """A document's identity: WB's own service name, else its file name."""
    return str(item.get("serviceName") or item.get("name") or "")


__all__ = [
    "fetch_claims",
    "fetch_documents",
    "fetch_feedbacks",
    "fetch_orders",
    "fetch_questions",
]
