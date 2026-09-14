"""Walks over feeds WB serves as a stream or a page, not as a date window.

Three shapes live here: a cursor stream (orders), a snapshot whose whole content
is the answer (claims), and take/skip paging (reviews, questions, documents).
Each returns rows and a resume point; none of them touches the database.
"""

from __future__ import annotations

from typing import Any

from src.integrations.wildberries.clients.reference import WBReferenceClient
from src.modules.guide.services.fetch.common import (
    CapturedRow,
    CaptureResult,
    CaptureWindow,
    as_rows,
    parse_day,
    windows,
)

#: WB caps one ``supplier/orders`` response at 80 000 rows and offers no page
#: parameter: the next page is the same request from the last row's
#: ``lastChangeDate``. A response shorter than this is therefore the last one.
_ORDERS_PAGE_LIMIT = 80000

#: The orders cursor only accepts ``lastChangeDate``, which is not unique, so
#: consecutive pages overlap by however many rows share the boundary second.
#: Rows are keyed by ``srid``, so the overlap upserts onto itself instead of
#: duplicating — and the walk stops if a full page fails to advance the cursor,
#: which would otherwise loop forever.
_ORDERS_PATH = "/api/v1/supplier/orders"


async def fetch_orders(client: WBReferenceClient, window: CaptureWindow) -> CaptureResult:
    """Walk the orders stream forward from the last ``lastChangeDate`` seen.

    On a first run this starts at the floor WB still serves rather than at the
    module's history floor: the cursor form of this feed refuses anything older
    than about 181 days, and asking for 2024 simply returns the same first row
    as asking for the cliff.

    Args:
        client: Reference client on the statistics host.
        window: Previous cursor and this run's page budget.

    Returns:
        Every order row whose ``lastChangeDate`` moved since the last run, and
        the newest ``lastChangeDate`` seen as the next cursor.
    """
    cursor = window.cursor or f"{window.floor.isoformat()}T00:00:00"
    rows: list[CapturedRow] = []
    newest = cursor
    for _ in range(max(1, window.max_pages)):
        payload = await client.get(_ORDERS_PATH, {"dateFrom": cursor, "flag": 0})
        page = as_rows(
            payload,
            key_of=lambda item: item["srid"],
            day_of=lambda item: parse_day(item.get("date")),
        )
        rows.extend(page)
        if not isinstance(payload, list) or len(payload) < _ORDERS_PAGE_LIMIT:
            break
        page_max = max(
            (str(item.get("lastChangeDate") or "") for item in payload if isinstance(item, dict)),
            default="",
        )
        if not page_max or page_max <= cursor:
            # A full page that did not advance the cursor: asking again would
            # return the same rows forever. Stop and keep what we have.
            break
        cursor = page_max
        newest = page_max
    for _, _, payload_row in rows:
        stamp = str(payload_row.get("lastChangeDate") or "")
        if stamp > newest:
            newest = stamp
    return CaptureResult(rows=rows, cursor=newest)


async def fetch_claims(client: WBReferenceClient, window: CaptureWindow) -> CaptureResult:
    """Capture every return claim WB still holds, open and archived.

    There is no cursor and no window: WB keeps fourteen days and serves all of
    it, so each run re-reads the whole thing and upserts. That is also why this
    runs daily — a fortnight is the entire memory of this feed.

    Args:
        client: Reference client on the returns host.
        window: Unused beyond the row cap; the feed has no date parameters.

    Returns:
        Open and archived claims, keyed by claim id.
    """
    rows: list[CapturedRow] = []
    for archived in ("true", "false"):
        payload = await client.get(
            "/api/v1/claims",
            {"is_archive": archived, "limit": 200, "offset": 0},
        )
        claims = payload.get("claims") if isinstance(payload, dict) else None
        rows.extend(
            as_rows(
                claims,
                key_of=lambda item: item["id"],
                day_of=lambda item: parse_day(item.get("dt")),
            )
        )
    return CaptureResult(rows=rows)


async def _take_skip(
    client: WBReferenceClient,
    window: CaptureWindow,
    *,
    path: str,
    envelope: str,
    date_field: str,
) -> CaptureResult:
    """Walk a ``take``/``skip`` feed oldest-first, resuming from the last offset.

    Oldest-first (``order=dateAsc``) rather than newest-first, because the
    offset is only a stable resume point when new rows land at the END of the
    sequence. Newest-first would shift every offset each time a review arrived,
    and the walk would re-read and miss rows in the same pass.
    """
    skip = int(window.cursor) if window.cursor and window.cursor.isdigit() else 0
    take = 1000
    rows: list[CapturedRow] = []
    while len(rows) < window.max_rows:
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
        rows.extend(page)
        if not isinstance(items, list) or len(items) < take:
            skip += len(page)
            break
        skip += len(page)
    return CaptureResult(rows=rows, cursor=str(skip))


async def fetch_feedbacks(client: WBReferenceClient, window: CaptureWindow) -> CaptureResult:
    """Capture answered reviews, oldest first, resuming from the last offset."""
    return await _take_skip(
        client, window, path="/api/v1/feedbacks", envelope="feedbacks", date_field="createdDate"
    )


async def fetch_questions(client: WBReferenceClient, window: CaptureWindow) -> CaptureResult:
    """Capture answered buyer questions, on the same walk as reviews."""
    return await _take_skip(
        client, window, path="/api/v1/questions", envelope="questions", date_field="createdDate"
    )


async def fetch_documents(client: WBReferenceClient, window: CaptureWindow) -> CaptureResult:
    """Capture the document index, one bounded window of history per run.

    WB pages this fifty at a time and returns the NEWEST fifty of whatever
    window it is asked for, so paging by offset is not available — the walk is
    by date window instead, oldest first, and ``captured_through`` carries it.
    """
    start = window.resume_from()
    end = window.yesterday
    if start > end:
        return CaptureResult(rows=[], captured_through=window.captured_through)
    rows: list[CapturedRow] = []
    covered = start
    for begin, stop in windows(start, end, span_days=31, limit=window.max_windows):
        payload = await client.get(
            "/api/v1/documents/list",
            {"locale": "ru", "beginTime": begin.isoformat(), "endTime": stop.isoformat()},
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        documents = data.get("documents") if isinstance(data, dict) else None
        rows.extend(
            as_rows(
                documents,
                key_of=_document_key,
                day_of=lambda item: parse_day(item.get("creationTime")),
            )
        )
        covered = stop
    return CaptureResult(rows=rows, captured_through=covered)


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
