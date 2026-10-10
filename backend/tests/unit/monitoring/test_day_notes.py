"""Unit tests for the per-day rows under the matrix (services/analytics/).

Covers the note contract — header and comment are independent fields, and the
day's row lives while either of them does — the «Действия» day-action
save/clear round-trip, the campaign-level «ДРР от продаж», and the operating
day boundary that decides which column a carried header lands on.

The header CARRY itself is a single set-based statement in the repository, so
it is exercised against a real database rather than mocked here.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from src.core.timeutils import MOSCOW_TZ, operating_today
from src.modules.monitoring.schemas.day_actions import DayActionState
from src.modules.monitoring.schemas.matrix import (
    MATRIX_BUCKETS,
    MatrixBaseState,
    MatrixDayBase,
    MatrixFunnelBase,
)
from src.modules.monitoring.services.analytics import AnalyticsService
from src.modules.monitoring.services.matrix import build_matrix_from_base
from tests.support.matrix_rows import _ad_bucket

NM_ID = 111
MANAGER = uuid.UUID("019f0000-0000-7000-8000-000000000001")


class _Row:
    """Stand-in for a ``SkuDayComment`` ORM row."""

    def __init__(self, body: str = "", header: str = "") -> None:
        self.body = body
        self.header = header


class _FakeCommentRepo:
    """In-memory stand-in for ``SkuDayCommentRepository``."""

    def __init__(self, rows: dict[date, _Row] | None = None) -> None:
        self.rows: dict[date, _Row] = rows or {}

    async def get(self, *, nm_id: int, comment_date: date) -> _Row | None:
        return self.rows.get(comment_date)

    async def set(self, *, nm_id: int, comment_date: date, body: str, header: str) -> None:
        self.rows[comment_date] = _Row(body=body, header=header)

    async def clear(self, *, nm_id: int, comment_date: date) -> None:
        self.rows.pop(comment_date, None)


class _FakeActionRepo:
    """In-memory stand-in for ``SkuDayActionRepository`` and its history."""

    def __init__(self) -> None:
        self.rows: dict[date, dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []

    async def get(self, *, nm_id: int, action_date: date) -> SimpleNamespace | None:
        fields = self.rows.get(action_date)
        return None if fields is None else SimpleNamespace(**fields)

    async def set(self, *, nm_id: int, action_date: date, **fields: Any) -> None:
        self.rows[action_date] = fields

    async def clear(self, *, nm_id: int, action_date: date) -> None:
        self.rows.pop(action_date, None)

    async def record_change(self, **change: Any) -> None:
        self.history.append(change)


def _service(
    comments: _FakeCommentRepo | None = None, actions: _FakeActionRepo | None = None
) -> AnalyticsService:
    """Build the service with only the repos the note methods touch."""
    unused: Any = None
    return AnalyticsService(
        funnel_repo=unused,
        advertising_repo=unused,
        advertising_search_repo=unused,
        advertising_write_off_repo=unused,
        stock_repo=unused,
        campaign_repo=unused,
        product_card_repo=unused,
        product_size_repo=unused,
        matrix_override_repo=unused,
        price_repo=unused,
        sale_repo=unused,
        pinned_sku_repo=unused,
        day_comment_repo=comments or _FakeCommentRepo(),
        day_action_repo=actions or _FakeActionRepo(),
    )


# --------------------------------------------------------------------------- #
# Day notes: header and comment save independently
# --------------------------------------------------------------------------- #
DAY = date(2026, 7, 10)


@pytest.mark.asyncio
async def test_editing_one_field_leaves_the_other_untouched() -> None:
    """Header and comment are independent: an omitted field is not cleared."""
    repo = _FakeCommentRepo({DAY: _Row(body="Подняли ставку", header="Неделя акции")})
    service = _service(comments=repo)

    result = await service.set_day_note(nm_id=NM_ID, comment_date=DAY, body=" Снизили CPM ")

    assert result.note is not None
    assert result.note.body == "Снизили CPM"
    assert result.note.header == "Неделя акции"  # untouched by a body-only save
    assert repo.rows[DAY].header == "Неделя акции"

    await service.set_day_note(nm_id=NM_ID, comment_date=DAY, header="Новая неделя")

    assert repo.rows[DAY].body == "Снизили CPM"  # untouched by a header-only save
    assert repo.rows[DAY].header == "Новая неделя"


@pytest.mark.asyncio
async def test_a_header_only_day_is_stored() -> None:
    """A day may carry just a title — the comment is not required."""
    repo = _FakeCommentRepo()
    result = await _service(comments=repo).set_day_note(
        nm_id=NM_ID, comment_date=DAY, header=" Распродажа "
    )
    assert result.note is not None
    assert (result.note.header, result.note.body) == ("Распродажа", "")
    assert repo.rows[DAY].header == "Распродажа"


@pytest.mark.asyncio
async def test_clearing_one_field_keeps_the_row_and_both_deletes_it() -> None:
    """The row lives while either field does; emptying both removes it."""
    repo = _FakeCommentRepo({DAY: _Row(body="Подняли ставку", header="Неделя акции")})
    service = _service(comments=repo)

    await service.set_day_note(nm_id=NM_ID, comment_date=DAY, body="")

    assert DAY in repo.rows  # the header still holds the row open
    assert repo.rows[DAY].header == "Неделя акции"

    result = await service.set_day_note(nm_id=NM_ID, comment_date=DAY, header="  ")

    assert result.note is None
    assert DAY not in repo.rows


# --------------------------------------------------------------------------- #
# Day actions («Действия»)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_day_action_save_and_full_clear() -> None:
    """A partial answer stores the full state; clearing every answer deletes."""
    repo = _FakeActionRepo()
    service = _service(actions=repo)
    day = date(2026, 7, 10)

    saved = await service.set_day_action(
        nm_id=NM_ID,
        action_date=day,
        action=DayActionState(first_rk_type="uni", first_rk_budget=1500.0, price_change="down"),
        changed_by=MANAGER,
    )
    assert saved.action is not None
    assert saved.action.first_rk_type == "uni"
    assert repo.rows[day]["first_rk_budget"] == 1500.0
    assert repo.rows[day]["second_rk_type"] is None

    cleared = await service.set_day_action(
        nm_id=NM_ID, action_date=day, action=DayActionState(), changed_by=MANAGER
    )
    assert cleared.action is None
    assert day not in repo.rows


@pytest.mark.asyncio
async def test_every_day_action_change_is_kept_with_who_and_what_was_there() -> None:
    """Creating, changing and clearing a day each leave a before/after record.

    The action row keeps only the last state, so without this a day saved to
    the wrong column (11.09 for 09.10, 2026-10-09) left no trace of what that
    column held before or who overwrote it.
    """
    repo = _FakeActionRepo()
    service = _service(actions=repo)
    day = date(2026, 10, 9)
    other = uuid.UUID("019f0000-0000-7000-8000-000000000002")

    await service.set_day_action(
        nm_id=NM_ID,
        action_date=day,
        action=DayActionState(first_rk_type="uni", first_rk_budget=1200.0),
        changed_by=MANAGER,
    )
    await service.set_day_action(
        nm_id=NM_ID,
        action_date=day,
        action=DayActionState(first_rk_type="uni", first_rk_budget=4000.0),
        changed_by=other,
    )
    await service.set_day_action(
        nm_id=NM_ID, action_date=day, action=DayActionState(), changed_by=MANAGER
    )

    created, changed, cleared = repo.history
    assert created["before"] is None
    assert created["after"]["first_rk_budget"] == 1200.0
    assert created["changed_by"] == MANAGER
    assert changed["before"]["first_rk_budget"] == 1200.0
    assert changed["after"]["first_rk_budget"] == 4000.0
    assert changed["changed_by"] == other
    assert cleared["before"]["first_rk_budget"] == 4000.0
    assert cleared["after"] is None
    assert {entry["action_date"] for entry in repo.history} == {day}


@pytest.mark.asyncio
async def test_a_save_that_changes_nothing_is_not_recorded() -> None:
    """Re-sending the stored state (a blur on an untouched field) adds no record."""
    repo = _FakeActionRepo()
    service = _service(actions=repo)
    day = date(2026, 10, 9)
    state = DayActionState(first_rk_type="uni", first_rk_budget=1200.0)

    await service.set_day_action(nm_id=NM_ID, action_date=day, action=state, changed_by=MANAGER)
    await service.set_day_action(nm_id=NM_ID, action_date=day, action=state, changed_by=MANAGER)
    await service.set_day_action(
        nm_id=NM_ID, action_date=day, action=DayActionState(), changed_by=MANAGER
    )
    await service.set_day_action(
        nm_id=NM_ID, action_date=day, action=DayActionState(), changed_by=MANAGER
    )

    assert [(e["before"] is None, e["after"] is None) for e in repo.history] == [
        (True, False),
        (False, True),
    ]


def test_the_two_rk_slots_cannot_hold_the_same_type() -> None:
    """The synced dropdowns never repeat a type; a malformed request is rejected."""
    with pytest.raises(ValueError, match="different campaign types"):
        DayActionState(first_rk_type="uni", second_rk_type="uni")


# --------------------------------------------------------------------------- #
# «ДРР от продаж» merged per campaign
# --------------------------------------------------------------------------- #
def _cell(matrix: Any, key: str, bucket: str) -> float | None:
    row = next(r for r in matrix.rows if r.key == key)
    return row.values[MATRIX_BUCKETS.index(bucket)]


def test_drr_sales_uses_the_campaigns_own_buyout_volume() -> None:
    """Every zone of a campaign carries ONE value: its spend / ITS buyouts.

    The campaign delivered 4 orders (3 search + 1 shelves) at 100 ₽ against a
    50% buyout percent -> 200 ₽ of buyouts for 250 ₽ of spend = 125%. The SKU's
    whole day is far bigger (10 orders -> 500 ₽ of buyouts); dividing by THAT
    prints 50% and flatters a campaign that is in fact underwater.
    """
    base = MatrixBaseState(
        days=[
            MatrixDayBase(
                day=date(2026, 7, 10),
                has_advertising=True,
                buckets={
                    "uni_search": _ad_bucket(views=100, clicks=10, spend=100.0, orders=3),
                    "uni_shelves": _ad_bucket(views=300, clicks=20, spend=150.0, orders=1),
                },
                funnel=MatrixFunnelBase(
                    open_count=100,
                    cart_count=30,
                    order_count=10,
                    seller_price=100.0,
                    price_currency="RUB",
                ),
                lagged_buyout_percent=50.0,
            )
        ]
    )
    matrix = build_matrix_from_base(base)
    # (100 + 150) / ((3 + 1) x 100 ₽ x 50%) = 250 / 200 = 125%, on both zones.
    assert _cell(matrix, "drr_sales", "uni_search") == 125.0
    assert _cell(matrix, "drr_sales", "uni_shelves") == 125.0
    # A group that never delivered stays empty.
    assert _cell(matrix, "drr_sales", "manual_search") is None
    # «Общая» keeps its SKU-wide reading: all ad spend / the day's buyouts.
    assert _cell(matrix, "drr_sales", "total") == 50.0  # 250 / 500


# --------------------------------------------------------------------------- #
# The operating day boundary (21:00 MSK = 00:00 Bishkek)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("moscow_clock", "expected"),
    [
        ("2026-07-20T20:59:00", date(2026, 7, 20)),  # still the 20th for the team
        ("2026-07-20T21:00:00", date(2026, 7, 21)),  # their new day begins
        ("2026-07-20T23:30:00", date(2026, 7, 21)),  # ...and Moscow is still the 20th
        ("2026-07-21T00:30:00", date(2026, 7, 21)),  # Moscow catches up
    ],
)
def test_operating_day_turns_over_at_21_msk(moscow_clock: str, expected: date) -> None:
    """The team's date advances at 21:00 MSK — the instant the beat fires.

    This is what decides which column a carried header lands on: between 21:00
    and 24:00 MSK the operating date is already one day ahead of Moscow's.
    """
    moment = datetime.fromisoformat(moscow_clock).replace(tzinfo=MOSCOW_TZ)

    assert operating_today(moment) == expected
