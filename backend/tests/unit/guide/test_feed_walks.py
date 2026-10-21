"""What each captured feed's walk does with WB's answers, and what it holds.

The client is a hand-written fake rather than a mock: a renamed method on the
real client must break these tests, which is the whole reason the walks are
written to take a client instead of building one.

Since 2026-09-17 a walk YIELDS batches instead of returning a run, so two kinds
of property live here. The old ones — which requests are made, what the cursor
does, how a window budget is spent — and a new one that had no home before:
**nothing accumulates**. That is what the orders feed was killed for not doing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import pytest

from src.modules.guide.services.fetch import (
    CaptureBatch,
    CapturedRow,
    CaptureWindow,
    fetch_claims,
    fetch_documents,
    fetch_feedbacks,
    fetch_orders,
)

pytestmark = pytest.mark.asyncio

_TODAY = date(2026, 9, 12)


class FakeReferenceClient:
    """Answers canned payloads and records every request it was asked for."""

    def __init__(self, answers: list[Any]) -> None:
        """Queue one answer per expected call, in order."""
        self._answers = list(answers)
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        #: Batch sizes the walk asked for, so a test can pin that it streams.
        self.batch_sizes: list[int] = []

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Record the call and return the next canned answer."""
        self.calls.append((path, params))
        return self._answers.pop(0) if self._answers else None

    async def stream(
        self, path: str, params: dict[str, Any] | None = None, *, batch_size: int = 2_000
    ) -> AsyncIterator[list[Any]]:
        """Serve the next canned list in batches, as the real client does."""
        self.calls.append((path, params))
        self.batch_sizes.append(batch_size)
        payload = self._answers.pop(0) if self._answers else None
        if not isinstance(payload, list):
            return
        for start in range(0, len(payload), batch_size):
            yield payload[start : start + batch_size]

    async def run_report(self, path: str, params: dict[str, Any]) -> Any:
        """Record the call and return the next canned answer."""
        self.calls.append((path, params))
        return self._answers.pop(0) if self._answers else None


def _order(srid: str, changed: str, ordered: str = "2026-09-10T08:00:00") -> dict[str, Any]:
    """One order row, trimmed to the fields the walk actually reads."""
    return {"srid": srid, "lastChangeDate": changed, "date": ordered, "isCancel": False}


async def _drain(walk: AsyncIterator[CaptureBatch]) -> tuple[list[CapturedRow], CaptureBatch]:
    """Collect a whole walk, the way `capture` would if it stored nothing.

    Returns every row in order and the LAST batch, which carries the watermark
    the run ends on.
    """
    rows: list[CapturedRow] = []
    last = CaptureBatch()
    async for batch in walk:
        rows.extend(batch.rows)
        last = CaptureBatch(
            rows=[],
            cursor=batch.cursor if batch.cursor is not None else last.cursor,
            captured_through=(
                batch.captured_through
                if batch.captured_through is not None
                else last.captured_through
            ),
        )
    return rows, last


async def test_the_orders_walk_carries_the_newest_change_forward_as_its_cursor() -> None:
    """The next run resumes from the newest ``lastChangeDate`` this one saw.

    The cursor is the only resume point WB offers on this feed, so losing it
    means either re-reading 188 days or silently skipping the gap.
    """
    client = FakeReferenceClient(
        [[_order("a", "2026-09-11T10:00:00"), _order("b", "2026-09-11T23:40:00")]]
    )

    rows, last = await _drain(fetch_orders(client, CaptureWindow(today=_TODAY)))  # type: ignore[arg-type]

    assert [key for key, _, _ in rows] == ["a", "b"]
    assert last.cursor == "2026-09-11T23:40:00"


async def test_the_orders_walk_never_holds_more_than_one_batch() -> None:
    """The property the 2026-09-16 OOM kill was the absence of.

    A full page is 80 000 rows and a decoded WB order is ~2.5 KB of Python, so
    a walk that hands its caller one page has already spent 200 MB of a 768 MiB
    worker — and the budget allows eight pages. What bounds this now is the
    batch, so the largest list the walk ever holds must stay at that size no
    matter how long the page is.
    """
    page = [_order(f"s{index}", "2026-06-01T00:00:00") for index in range(5_000)]
    client = FakeReferenceClient([page, []])

    largest = 0
    async for batch in fetch_orders(client, CaptureWindow(today=_TODAY, max_pages=2)):  # type: ignore[arg-type]
        largest = max(largest, len(batch.rows))

    assert largest == client.batch_sizes[0]
    assert largest < len(page)


async def test_the_orders_walk_moves_its_cursor_only_between_pages() -> None:
    """Mid-page the walk cannot name a safe resume point, so it names none.

    WB does not order a page by ``lastChangeDate``: this one's newest row comes
    first. A batch that carried "the newest seen so far" would let a crash
    resume past every older row behind it — rows that were captured but never
    stored.
    """
    page = [_order("newest", "2026-09-11T23:00:00")] + [
        _order(f"s{index}", "2026-06-01T00:00:00") for index in range(3_000)
    ]
    client = FakeReferenceClient([page, []])

    batches = [
        batch
        async for batch in fetch_orders(client, CaptureWindow(today=_TODAY, max_pages=1))  # type: ignore[arg-type]
    ]

    assert [batch.cursor for batch in batches if batch.rows] == [None, None]
    assert batches[-1].cursor == "2026-09-11T23:00:00"
    assert not batches[-1].rows


async def test_the_orders_walk_pages_until_a_short_page_arrives() -> None:
    """A full 80 000-row response means more rows exist behind it.

    Seen 2026-09-12: one request returned exactly 80 000 rows and
    stopped seventeen days short of today. Treating that as the whole feed is
    the failure mode this pins.
    """
    full_page = [_order(f"s{i}", "2026-06-01T00:00:00") for i in range(80000)]
    full_page[-1]["lastChangeDate"] = "2026-07-01T00:00:00"
    client = FakeReferenceClient([full_page, [_order("last", "2026-09-11T12:00:00")]])

    _rows, last = await _drain(
        fetch_orders(client, CaptureWindow(today=_TODAY, max_pages=4))  # type: ignore[arg-type]
    )

    assert len(client.calls) == 2
    assert client.calls[1][1] == {"dateFrom": "2026-07-01T00:00:00", "flag": 0}
    assert last.cursor == "2026-09-11T12:00:00"


async def test_a_full_page_that_does_not_advance_the_cursor_stops_the_walk() -> None:
    """More than 80 000 rows sharing one timestamp must not loop forever.

    The cursor is a timestamp with no record-id component, so a page whose
    newest stamp equals the one asked for would be requested again identically.
    """
    stuck_page = [_order(f"s{i}", "2026-06-01T00:00:00") for i in range(80000)]
    client = FakeReferenceClient([stuck_page, stuck_page, stuck_page])

    rows, _last = await _drain(
        fetch_orders(  # type: ignore[arg-type]
            client,
            CaptureWindow(today=_TODAY, cursor="2026-06-01T00:00:00", max_pages=4),
        )
    )

    assert len(client.calls) == 1
    assert rows


async def test_claims_are_captured_open_and_archived_in_one_run() -> None:
    """Both halves, because WB splits them and keeps each only fourteen days."""
    client = FakeReferenceClient(
        [
            {"claims": [{"id": "c1", "dt": "2026-08-29T18:14:36.239416", "nm_id": 1}]},
            {"claims": [{"id": "c2", "dt": "2026-09-11T21:08:39.459786", "nm_id": 2}]},
        ]
    )

    rows, _last = await _drain(fetch_claims(client, CaptureWindow(today=_TODAY)))  # type: ignore[arg-type]

    assert [key for key, _, _ in rows] == ["c1", "c2"]
    assert [params["is_archive"] for _, params in client.calls if params] == ["true", "false"]
    assert rows[0][1] == date(2026, 8, 29)


async def test_a_feed_with_no_rows_captures_nothing_and_moves_no_cursor() -> None:
    """An empty answer is a quiet account, not a failure to record."""
    client = FakeReferenceClient([{"claims": []}, {"claims": []}])

    rows, last = await _drain(fetch_claims(client, CaptureWindow(today=_TODAY)))  # type: ignore[arg-type]

    assert rows == []
    assert last.cursor is None


async def test_reviews_are_walked_oldest_first_and_resume_by_offset() -> None:
    """Oldest-first is what makes the offset a stable resume point.

    Newest-first would shift every offset each time a review arrived, so the
    next run would re-read some rows and skip others in the same pass.
    """
    client = FakeReferenceClient(
        [{"data": {"feedbacks": [{"id": "f1", "createdDate": "2025-06-07T13:54:30Z"}]}}]
    )

    _rows, last = await _drain(
        fetch_feedbacks(client, CaptureWindow(today=_TODAY, cursor="40"))  # type: ignore[arg-type]
    )

    _path, params = client.calls[0]
    assert params is not None
    assert params["order"] == "dateAsc"
    assert params["skip"] == 40
    assert last.cursor == "41"


async def test_the_document_index_walks_windows_and_records_how_far_it_got() -> None:
    """WB returns the newest fifty of any window, so the walk is by date.

    Paging by offset is not available here; ``captured_through`` is what stops
    the next run re-reading the same months — and it records where the WINDOW
    budget ran out, not where the walk wished it could reach.
    """
    client = FakeReferenceClient(
        [
            {
                "data": {
                    "documents": [{"serviceName": "upd-1", "creationTime": "2026-07-05T00:00:00Z"}]
                }
            },
            {"data": {"documents": []}},
        ]
    )

    rows, last = await _drain(
        fetch_documents(  # type: ignore[arg-type]
            client,
            CaptureWindow(today=_TODAY, captured_through=date(2026, 7, 1), max_windows=2),
        )
    )

    assert [key for key, _, _ in rows] == ["upd-1"]
    assert last.captured_through == date(2026, 9, 1)


async def test_each_window_of_a_walk_carries_its_own_watermark() -> None:
    """A run cut short keeps the windows it finished, rather than all or nothing.

    Before batches, a walk that raised on its fourth window threw the first
    three away and re-read them next month. That was survivable while the whole
    thing was one return value; with the rows stored as they arrive it would be
    worse than survivable — the rows would be in the database with a watermark
    that disowned them.
    """
    client = FakeReferenceClient(
        [
            {"data": {"documents": [{"serviceName": "a", "creationTime": "2026-07-05"}]}},
            {"data": {"documents": [{"serviceName": "b", "creationTime": "2026-08-05"}]}},
        ]
    )

    marks = [
        batch.captured_through
        async for batch in fetch_documents(  # type: ignore[arg-type]
            client,
            CaptureWindow(today=_TODAY, captured_through=date(2026, 7, 1), max_windows=2),
        )
    ]

    assert marks == [date(2026, 8, 1), date(2026, 9, 1)]
