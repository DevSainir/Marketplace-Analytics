"""What each captured feed's walk does with WB's answers.

The client is a hand-written fake rather than a mock: a renamed method on the
real client must break these tests, which is the whole reason the walks are
written to take a client instead of building one.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from src.modules.guide.services.fetch import (
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

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Record the call and return the next canned answer."""
        self.calls.append((path, params))
        return self._answers.pop(0) if self._answers else None

    async def run_report(self, path: str, params: dict[str, Any]) -> Any:
        """Record the call and return the next canned answer."""
        self.calls.append((path, params))
        return self._answers.pop(0) if self._answers else None


def _order(srid: str, changed: str, ordered: str = "2026-09-10T08:00:00") -> dict[str, Any]:
    """One order row, trimmed to the fields the walk actually reads."""
    return {"srid": srid, "lastChangeDate": changed, "date": ordered, "isCancel": False}


async def test_the_orders_walk_carries_the_newest_change_forward_as_its_cursor() -> None:
    """The next run resumes from the newest ``lastChangeDate`` this one saw.

    The cursor is the only resume point WB offers on this feed, so losing it
    means either re-reading 188 days or silently skipping the gap.
    """
    client = FakeReferenceClient(
        [[_order("a", "2026-09-11T10:00:00"), _order("b", "2026-09-11T23:40:00")]]
    )

    result = await fetch_orders(client, CaptureWindow(today=_TODAY))  # type: ignore[arg-type]

    assert [key for key, _, _ in result.rows] == ["a", "b"]
    assert result.cursor == "2026-09-11T23:40:00"


async def test_the_orders_walk_pages_until_a_short_page_arrives() -> None:
    """A full 80 000-row response means more rows exist behind it.

    Measured on prod 2026-09-12: one request returned exactly 80 000 rows and
    stopped seventeen days short of today. Treating that as the whole feed is
    the failure mode this pins.
    """
    full_page = [_order(f"s{i}", "2026-06-01T00:00:00") for i in range(80000)]
    full_page[-1]["lastChangeDate"] = "2026-07-01T00:00:00"
    client = FakeReferenceClient([full_page, [_order("last", "2026-09-11T12:00:00")]])

    result = await fetch_orders(client, CaptureWindow(today=_TODAY, max_pages=4))  # type: ignore[arg-type]

    assert len(client.calls) == 2
    assert client.calls[1][1] == {"dateFrom": "2026-07-01T00:00:00", "flag": 0}
    assert result.cursor == "2026-09-11T12:00:00"


async def test_a_full_page_that_does_not_advance_the_cursor_stops_the_walk() -> None:
    """More than 80 000 rows sharing one timestamp must not loop forever.

    The cursor is a timestamp with no record-id component, so a page whose
    newest stamp equals the one asked for would be requested again identically.
    """
    stuck_page = [_order(f"s{i}", "2026-06-01T00:00:00") for i in range(80000)]
    client = FakeReferenceClient([stuck_page, stuck_page, stuck_page])

    result = await fetch_orders(
        client,  # type: ignore[arg-type]
        CaptureWindow(today=_TODAY, cursor="2026-06-01T00:00:00", max_pages=4),
    )

    assert len(client.calls) == 1
    assert result.rows


async def test_claims_are_captured_open_and_archived_in_one_run() -> None:
    """Both halves, because WB splits them and keeps each only fourteen days."""
    client = FakeReferenceClient(
        [
            {"claims": [{"id": "c1", "dt": "2026-08-29T18:14:36.239416", "nm_id": 1}]},
            {"claims": [{"id": "c2", "dt": "2026-09-11T21:08:39.459786", "nm_id": 2}]},
        ]
    )

    result = await fetch_claims(client, CaptureWindow(today=_TODAY))  # type: ignore[arg-type]

    assert [key for key, _, _ in result.rows] == ["c1", "c2"]
    assert [params["is_archive"] for _, params in client.calls if params] == ["true", "false"]
    assert result.rows[0][1] == date(2026, 8, 29)


async def test_a_feed_with_no_rows_captures_nothing_and_moves_no_cursor() -> None:
    """An empty answer is a quiet account, not a failure to record."""
    client = FakeReferenceClient([{"claims": []}, {"claims": []}])

    result = await fetch_claims(client, CaptureWindow(today=_TODAY))  # type: ignore[arg-type]

    assert result.rows == []
    assert result.cursor is None


async def test_reviews_are_walked_oldest_first_and_resume_by_offset() -> None:
    """Oldest-first is what makes the offset a stable resume point.

    Newest-first would shift every offset each time a review arrived, so the
    next run would re-read some rows and skip others in the same pass.
    """
    client = FakeReferenceClient(
        [{"data": {"feedbacks": [{"id": "f1", "createdDate": "2025-06-07T13:54:30Z"}]}}]
    )

    result = await fetch_feedbacks(client, CaptureWindow(today=_TODAY, cursor="40"))  # type: ignore[arg-type]

    _path, params = client.calls[0]
    assert params is not None
    assert params["order"] == "dateAsc"
    assert params["skip"] == 40
    assert result.cursor == "41"


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

    result = await fetch_documents(
        client,  # type: ignore[arg-type]
        CaptureWindow(today=_TODAY, captured_through=date(2026, 7, 1), max_windows=2),
    )

    assert [key for key, _, _ in result.rows] == ["upd-1"]
    assert result.captured_through == date(2026, 9, 1)
