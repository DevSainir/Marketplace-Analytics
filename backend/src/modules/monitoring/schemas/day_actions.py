"""DTOs for the per-day action row («Действия» under the matrix comments).

The manager records, per day: up to two advertising campaigns («Первая РК» /
«Вторая РК»), each a campaign TYPE with its «Бюджет рекламы», and whether the
price was moved («Меняли цену?» direction + «На сколько»). Every field is
optional — an unset answer is ``None``.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

#: An ad campaign type: «Единая» / «Руч. поиск» / «Руч. полки» / «CPC».
RkType = Literal["uni", "manual_search", "manual_shelves", "cpc"]

#: «Меняли цену?» answers: raised / lowered (no «Нет» — an unmoved price is
#: simply left unanswered).
PriceChange = Literal["up", "down"]


class DayActionState(BaseModel):
    """The full answered state of one SKU-day's action row.

    Used both as the update request (the frontend PUTs the WHOLE day state —
    last write wins, same as the comment note) and as the per-day value in the
    detail response's ``day_actions`` map.
    """

    first_rk_type: RkType | None = Field(
        default=None, description="«Первая РК» campaign type, null when unset."
    )
    first_rk_budget: float | None = Field(
        default=None, ge=0, description="First campaign «Бюджет рекламы», rubles."
    )
    second_rk_type: RkType | None = Field(
        default=None, description="«Вторая РК» campaign type, null when unset."
    )
    second_rk_budget: float | None = Field(
        default=None, ge=0, description="Second campaign «Бюджет рекламы», rubles."
    )
    price_change: PriceChange | None = Field(
        default=None,
        description="«Меняли цену?» — up (повысили) / down (понизили).",
    )
    price_change_amount: float | None = Field(
        default=None, ge=0, description="«На сколько» — the price difference, rubles."
    )

    @model_validator(mode="after")
    def _distinct_rk_types(self) -> DayActionState:
        """Reject the same campaign type in both ad campaign slots.

        The two dropdowns are synced on screen, so this only fires on a
        malformed request — but a day claiming «Единая» twice is meaningless,
        and enforcing it here keeps the store the single source of truth.
        """
        if self.first_rk_type is not None and self.first_rk_type == self.second_rk_type:
            raise ValueError("«Первая РК» and «Вторая РК» must be different campaign types.")
        return self

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
