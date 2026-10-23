"""DTOs for the per-day action row ("Actions" under the matrix comments).

The manager records, per day: up to two advertising campaigns ("First campaign" /
"Second campaign"), each a campaign TYPE with its "Ad budget", and whether the
price was moved ("Price changed?" direction + "By how much"). Every field is
optional — an unset answer is ``None``.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from src.core.exceptions import UserInputError

#: An ad campaign type: "Unified bid" / "Manual search" / "Manual shelves" / "CPC".
RkType = Literal["uni", "manual_search", "manual_shelves", "cpc"]

#: "Price changed?" answers: raised / lowered (no "No" — an unmoved price is
#: simply left unanswered).
PriceChange = Literal["up", "down"]


class DayActionState(BaseModel):
    """The full answered state of one SKU-day's action row.

    Used both as the update request (the frontend PUTs the WHOLE day state —
    last write wins, same as the comment note) and as the per-day value in the
    detail response's ``day_actions`` map.
    """

    first_rk_type: RkType | None = Field(
        default=None, description="First campaign type, null when unset."
    )
    first_rk_budget: float | None = Field(
        default=None, ge=0, description="First campaign ad budget, rubles."
    )
    second_rk_type: RkType | None = Field(
        default=None, description="Second campaign type, null when unset."
    )
    second_rk_budget: float | None = Field(
        default=None, ge=0, description="Second campaign ad budget, rubles."
    )
    price_change: PriceChange | None = Field(
        default=None,
        description="Price changed? — up (raised) / down (lowered).",
    )
    price_change_amount: float | None = Field(
        default=None, ge=0, description="By how much — the price difference, rubles."
    )

    @model_validator(mode="after")
    def _distinct_rk_types(self) -> DayActionState:
        """Reject the same campaign type in both ad campaign slots.

        The two dropdowns are synced on screen, so this only fires on a
        malformed request — but a day claiming "Unified bid" twice is meaningless,
        and enforcing it here keeps the store the single source of truth.
        """
        if self.first_rk_type is not None and self.first_rk_type == self.second_rk_type:
            raise UserInputError("The first and second campaigns must be different campaign types.")
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
