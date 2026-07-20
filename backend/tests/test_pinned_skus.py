"""Unit tests for the pinned-SKU chip row (services/analytics.py).

Covers the reorder contract — which is the tenancy guard for
``PUT /pins/order``, since that endpoint takes its identifiers from the body
and so cannot use the ``WorkspaceSku`` path guard the other pin routes rely on
— and the chip-colour round-trip.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from src.core.exceptions import ValidationError
from src.modules.monitoring.models.pinned_skus import PinnedSku
from src.modules.monitoring.services.analytics import AnalyticsService

WORKSPACE = uuid.uuid4()


class _FakePinnedRepo:
    """In-memory stand-in for ``PinnedSkuRepository``."""

    def __init__(self, rows: list[PinnedSku]) -> None:
        self.rows = rows
        self.reorder_calls: list[list[int]] = []
        self.color_calls: list[tuple[int, str | None]] = []

    async def list_rows(self, *, workspace_id: uuid.UUID) -> list[PinnedSku]:
        return self.rows

    async def reorder(self, *, nm_ids: list[int]) -> None:
        self.reorder_calls.append(nm_ids)
        self.rows = sorted(self.rows, key=lambda row: nm_ids.index(row.nm_id))

    async def set_color(self, *, nm_id: int, color: str | None) -> None:
        self.color_calls.append((nm_id, color))
        for row in self.rows:
            if row.nm_id == nm_id:
                row.color = color


class _FakeCardRepo:
    """Stand-in for ``ProductCardRepository`` with an unsynced catalogue."""

    async def get_by_ids(self, nm_ids: list[int]) -> dict[int, Any]:
        return {}


def _service(pins: Any) -> AnalyticsService:
    """Build the service with only the repos the pin methods touch."""
    unused: Any = None
    cards: Any = _FakeCardRepo()
    return AnalyticsService(
        funnel_repo=unused,
        advertising_repo=unused,
        advertising_search_repo=unused,
        stock_repo=unused,
        campaign_repo=unused,
        product_card_repo=cards,
        product_size_repo=unused,
        matrix_override_repo=unused,
        price_repo=unused,
        sale_repo=unused,
        warehouse_mark_repo=unused,
        pinned_sku_repo=pins,
        day_comment_repo=unused,
        day_action_repo=unused,
    )


def _rows() -> list[PinnedSku]:
    """Three pinned rows in positions 0..2."""
    return [
        PinnedSku(nm_id=nm_id, sort_order=index, color=None)
        for index, nm_id in enumerate([10, 20, 30])
    ]


@pytest.mark.asyncio
async def test_reorder_writes_the_new_order() -> None:
    """A reorder of exactly the pinned set is persisted and echoed back."""
    pins = _FakePinnedRepo(_rows())

    result = await _service(pins).reorder_pins(workspace_id=WORKSPACE, nm_ids=[30, 10, 20])

    assert pins.reorder_calls == [[30, 10, 20]]
    assert [item.nm_id for item in result.items] == [30, 10, 20]


@pytest.mark.asyncio
async def test_reorder_rejects_a_sku_outside_the_workspace_pins() -> None:
    """An nm_id the workspace has not pinned cannot be positioned.

    This is what stops a caller from writing ``sort_order`` on another
    workspace's pin: the guard is the pinned set, not the path.
    """
    pins = _FakePinnedRepo(_rows())

    with pytest.raises(ValidationError):
        await _service(pins).reorder_pins(workspace_id=WORKSPACE, nm_ids=[10, 20, 30, 999])

    assert pins.reorder_calls == []


@pytest.mark.asyncio
async def test_reorder_rejects_a_stale_list() -> None:
    """A list missing a pin (a teammate pinned meanwhile) is rejected whole."""
    pins = _FakePinnedRepo(_rows())

    with pytest.raises(ValidationError):
        await _service(pins).reorder_pins(workspace_id=WORKSPACE, nm_ids=[10, 20])

    assert pins.reorder_calls == []


@pytest.mark.asyncio
async def test_set_color_paints_and_clears_one_chip() -> None:
    """A colour is stored on its chip, and ``None`` clears it again."""
    pins = _FakePinnedRepo(_rows())
    service = _service(pins)

    painted = await service.set_sku_color(workspace_id=WORKSPACE, nm_id=20, color="#dbeafe")
    assert [item.color for item in painted.items] == [None, "#dbeafe", None]

    cleared = await service.set_sku_color(workspace_id=WORKSPACE, nm_id=20, color=None)
    assert [item.color for item in cleared.items] == [None, None, None]
    assert pins.color_calls == [(20, "#dbeafe"), (20, None)]
