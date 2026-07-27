"""Unit tests for UUIDv7 primary keys and the WB/operating business clocks.

Both are load-bearing in ways that are easy to break silently:

* UUIDv7 keys must stay **time-ordered** — that ordering is the whole reason
  the platform does not use UUIDv4 (random keys scatter B-Tree inserts across
  the entire index).
* The two clocks answer different questions. ``moscow_today`` dates WB's data;
  ``operating_today`` is when the team's day turns over (Bishkek, UTC+6). Mixing
  them puts a carried note header in the wrong column for three hours every
  evening.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from src.core.ids import uuid7
from src.core.timeutils import MOSCOW_TZ, OPERATING_TZ, moscow_today, operating_today


def test_uuid7_is_a_version_7_uuid() -> None:
    """The generated value declares version 7 and the RFC 9562 variant."""
    generated = uuid7()

    assert generated.version == 7
    assert generated.variant == uuid.RFC_4122


def test_uuid7_values_sort_by_creation_order_across_milliseconds() -> None:
    """Ids minted ≥1 ms apart sort ascending — the B-Tree locality guarantee.

    Ordering is guaranteed *to millisecond resolution* only: the 12 ``rand_a``
    bits carry entropy rather than a monotonic counter, so ids born inside one
    millisecond may tie in either order. That is the documented contract and it
    is enough for index locality — a handful of same-millisecond keys still land
    together at the right edge of the index.
    """
    generated = []
    for _ in range(20):
        generated.append(uuid7())
        time.sleep(0.002)

    assert [u.int for u in generated] == sorted(u.int for u in generated)


def test_uuid7_timestamps_never_go_backwards() -> None:
    """Even within one millisecond the embedded timestamp is non-decreasing.

    This is the weaker property that holds for *every* pair of ids, and it is
    what keeps inserts appending to the right edge of the index.
    """
    timestamps = [uuid7().int >> 80 for _ in range(1000)]

    assert timestamps == sorted(timestamps)


def test_uuid7_values_are_unique_within_one_millisecond() -> None:
    """The random tail keeps ids distinct even when the timestamp repeats."""
    generated = [uuid7() for _ in range(1000)]

    assert len(set(generated)) == 1000


def test_uuid7_embeds_the_current_timestamp() -> None:
    """The leading 48 bits are the Unix time in milliseconds.

    This is what makes the key time-ordered *and* what a reader relies on when
    eyeballing an id's age in a support ticket.
    """
    before_ms = int(datetime.now(UTC).timestamp() * 1000)

    embedded_ms = uuid7().int >> 80

    after_ms = int(datetime.now(UTC).timestamp() * 1000)
    assert before_ms - 1 <= embedded_ms <= after_ms + 1


def test_moscow_today_follows_the_moscow_calendar() -> None:
    """WB dates its rows by the Moscow day, so the helper must too."""
    assert moscow_today() == datetime.now(tz=MOSCOW_TZ).date()


def test_operating_day_turns_over_three_hours_before_moscow() -> None:
    """At 22:00 MSK the team is already on the next date.

    This is the boundary that decides which column a carried note header lands
    on; ``date.today()`` on a UTC server gets it wrong twice over.
    """
    late_moscow_evening = datetime(2026, 7, 1, 22, 30, tzinfo=MOSCOW_TZ)

    assert operating_today(late_moscow_evening).isoformat() == "2026-07-02"


def test_operating_day_still_matches_moscow_during_the_working_day() -> None:
    """Before 21:00 MSK both clocks agree — the shift is an evening-only effect."""
    moscow_afternoon = datetime(2026, 7, 1, 14, 0, tzinfo=MOSCOW_TZ)

    assert operating_today(moscow_afternoon).isoformat() == "2026-07-01"


def test_operating_day_converts_from_any_timezone() -> None:
    """A UTC instant is converted, not read naively.

    Celery beat and the API can hand this function timestamps in UTC; reading
    the wall-clock fields without converting would be off by six hours.
    """
    utc_instant = datetime(2026, 7, 1, 19, 0, tzinfo=UTC)  # 01:00 next day in Bishkek

    assert operating_today(utc_instant) == utc_instant.astimezone(OPERATING_TZ).date()
    assert operating_today(utc_instant).isoformat() == "2026-07-02"
