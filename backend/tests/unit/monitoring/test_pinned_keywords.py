"""Unit tests for «Закрепить» — the standing phrases behind the position cards.

A hand-written fake stands in for the repository, so these pin the service's own
decisions: what a phrase is allowed to be, when two typings are the same pin, and
that pinning never silently discards the number a seller is watching.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from src.core.exceptions import NotFoundError, ValidationError
from src.modules.monitoring.models.pinned_keywords import PinnedKeyword
from src.modules.monitoring.services.analytics.pinned_keywords import PinnedKeywordService

NM_ID = 953770957


def _row(keyword: str, **overrides: Any) -> PinnedKeyword:
    """A stored pin with sane defaults."""
    row = PinnedKeyword(
        nm_id=NM_ID,
        keyword=keyword,
        normalized_query=overrides.get("normalized_query", ""),
        last_position=overrides.get("last_position"),
        last_positions_scanned=overrides.get("last_positions_scanned", 0),
        last_total_found=overrides.get("last_total_found", 0),
        last_truncated=overrides.get("last_truncated", False),
        last_checked_at=overrides.get("last_checked_at"),
    )
    row.created_at = overrides.get("created_at", datetime(2026, 8, 15, tzinfo=UTC))
    return row


class _FakePinRepo:
    """In-memory stand-in for PinnedKeywordRepository."""

    def __init__(self, rows: list[PinnedKeyword] | None = None) -> None:
        self.rows = rows or []
        self.pinned: list[str] = []
        self.unpinned: list[str] = []

    async def list_for_sku(self, *, nm_id: int) -> list[PinnedKeyword]:
        return [row for row in self.rows if row.nm_id == nm_id]

    async def list_for_workspace(self, **_: Any) -> list[PinnedKeyword]:
        return self.rows

    async def pin(self, *, nm_id: int, keyword: str) -> PinnedKeyword:
        self.pinned.append(keyword)
        existing = next((r for r in self.rows if r.keyword == keyword), None)
        if existing:
            return existing
        row = _row(keyword)
        self.rows.append(row)
        return row

    async def unpin(self, *, nm_id: int, keyword: str) -> int:
        self.unpinned.append(keyword)
        before = len(self.rows)
        self.rows = [r for r in self.rows if r.keyword != keyword]
        return before - len(self.rows)


def _service(repo: _FakePinRepo) -> PinnedKeywordService:
    return PinnedKeywordService(pinned_keyword_repo=repo)  # type: ignore[arg-type]


@pytest.mark.parametrize("raw", ["", "   ", "\n\t "])
async def test_a_blank_phrase_is_refused_rather_than_stored(raw: str) -> None:
    """An empty pin would be re-probed forever and could never rank."""
    with pytest.raises(ValidationError):
        await _service(_FakePinRepo()).pin(nm_id=NM_ID, keyword=raw)


async def test_a_phrase_longer_than_wb_searches_is_refused() -> None:
    """A pin that can never be checked is worse than no pin: it looks maintained."""
    with pytest.raises(ValidationError):
        await _service(_FakePinRepo()).pin(nm_id=NM_ID, keyword="я" * 101)


async def test_spacing_and_case_do_not_create_a_second_card() -> None:
    """«Носки  Мужские» and «носки мужские» are one question, so one pin.

    WB normalizes the phrase before ranking, so storing both would spend the rate
    budget twice to show the same number on two cards.
    """
    repo = _FakePinRepo()
    service = _service(repo)

    await service.pin(nm_id=NM_ID, keyword="Носки  Мужские")
    await service.pin(nm_id=NM_ID, keyword="носки мужские")

    assert repo.pinned == ["носки мужские", "носки мужские"]
    assert len(repo.rows) == 1


async def test_repinning_keeps_the_number_the_seller_is_watching() -> None:
    """Re-pinning must not blank a position: the phrase is the identity."""
    repo = _FakePinRepo([_row("носки мужские", last_position=12)])

    item = await _service(repo).pin(nm_id=NM_ID, keyword="носки мужские")

    assert item.position == 12


async def test_unpinning_something_that_is_not_pinned_is_an_error() -> None:
    """The UI and the stored list disagree; succeeding silently would hide that."""
    with pytest.raises(NotFoundError):
        await _service(_FakePinRepo()).unpin(nm_id=NM_ID, keyword="носки мужские")


async def test_never_checked_and_checked_but_absent_stay_distinguishable() -> None:
    """Two states that look identical if collapsed and mean opposite things.

    A pin made a minute ago has no number yet; a pin WB answered for and did not
    rank has a depth. Rendering both as "no position" would tell a seller their
    card ranks nowhere when nothing was ever asked.
    """
    checked = datetime(2026, 8, 15, 13, 37, tzinfo=UTC)
    repo = _FakePinRepo(
        [
            _row("свежая фраза"),
            _row("проверенная фраза", last_checked_at=checked, last_positions_scanned=300),
        ]
    )

    items = {item.keyword: item for item in (await _service(repo).list_for_sku(nm_id=NM_ID)).items}

    assert items["свежая фраза"].checked_at is None
    assert items["проверенная фраза"].checked_at == checked
    assert items["проверенная фраза"].position is None
    assert items["проверенная фраза"].positions_scanned == 300
