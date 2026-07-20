"""DTOs for the per-day action row («Действия» under the matrix comments).

Three per-day questions the manager answers about what was done that day:
«Включали РК единая?» / «Включали РК ручная?» (each with a «Бюджет рекламы»)
and «Меняли цену?» (direction + «На сколько»). Every field is optional — an
unanswered question is ``None``.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

#: «Меняли цену?» answers: повысили / понизили / нет.
PriceChange = Literal["up", "down", "none"]


class DayActionState(BaseModel):
    """The full answered state of one SKU-day's action row.

    Used both as the update request (the frontend PUTs the WHOLE day state —
    last write wins, same as the comment note) and as the per-day value in the
    detail response's ``day_actions`` map.
    """

    uni_rk_enabled: bool | None = Field(
        default=None, description="«Включали РК единая?» — да/нет, null when unanswered."
    )
    uni_rk_budget: float | None = Field(
        default=None, ge=0, description="Unified campaign «Бюджет рекламы», rubles."
    )
    manual_rk_enabled: bool | None = Field(
        default=None, description="«Включали РК ручная?» — да/нет, null when unanswered."
    )
    manual_rk_budget: float | None = Field(
        default=None, ge=0, description="Manual campaign «Бюджет рекламы», rubles."
    )
    price_change: PriceChange | None = Field(
        default=None,
        description="«Меняли цену?» — up (повысили) / down (понизили) / none (нет).",
    )
    price_change_amount: float | None = Field(
        default=None, ge=0, description="«На сколько» — the price difference, rubles."
    )

    def is_empty(self) -> bool:
        """True when every answer is ``None`` (the day's row should not exist)."""
        return all(value is None for value in self.model_dump().values())


class DayActionResponse(BaseModel):
    """One SKU-day's stored action state after a save.

    ``action`` is ``None`` when the save cleared every answer and the day's
    row was deleted.
    """

    nm_id: int = Field(description="WB SKU identifier.")
    action_date: date = Field(description="The day the actions describe.")
    action: DayActionState | None = Field(
        default=None, description="The stored state, or null after a full clear."
    )
