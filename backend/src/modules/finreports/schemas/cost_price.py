"""Request/response DTOs for the per-SKU cost-price editor.

The only write surface the ``finreports`` module exposes. Everything else in the
module is harvested from WildBerries and read-only; these figures come from the
seller, so the DTOs validate them rather than trusting them — a negative or
absurd cost silently poisons every margin on the P&L.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

#: Upper bound on a single unit's cost. Not a business rule — a typo guard. Costs
#: are entered in KGS and the seller's are ~700-900, so a five-digit slip
#: (795 → 79500) is caught here instead of surfacing as a negative margin later.
MAX_UNIT_COST = Decimal(10_000_000)


class CostPriceItem(BaseModel):
    """One SKU's stated cost of goods, as returned to the editor."""

    nm_id: int
    cost: Decimal
    currency: str
    vendor_code: str
    source: str
    note: str
    updated_at: datetime | None = None
    #: Units settled for this SKU across the workspace's whole history. Shown so
    #: the seller can tell which uncosted SKUs actually matter.
    sold_units: int = 0


class CostPriceListResponse(BaseModel):
    """Every cost price on file, plus the SKUs still missing one."""

    currency: str
    items: list[CostPriceItem]
    #: SKUs that have been sold but carry no cost — the P&L's blind spots,
    #: ordered by units sold so the most expensive omission is first.
    missing: list[CostPriceItem]


class CostPriceInput(BaseModel):
    """One cost price submitted by the seller."""

    nm_id: int = Field(gt=0, description="WB SKU identifier.")
    cost: Decimal = Field(
        ge=0, le=MAX_UNIT_COST, description="Cost of one unit including fulfilment."
    )
    currency: str = Field(default="KGS", min_length=1, max_length=8)
    vendor_code: str = Field(default="", max_length=128)
    note: str = Field(default="", max_length=256)

    @field_validator("currency")
    @classmethod
    def _upper(cls, value: str) -> str:
        """Normalise the currency code so ``kgs`` matches WB's ``KGS``."""
        return value.strip().upper()


class CostPriceBulkInput(BaseModel):
    """A batch of cost prices — the editor saves the whole grid at once."""

    items: list[CostPriceInput] = Field(min_length=1, max_length=5000)

    @field_validator("items")
    @classmethod
    def _unique_nm_ids(cls, items: list[CostPriceInput]) -> list[CostPriceInput]:
        """Reject a batch carrying two different costs for the same SKU.

        PostgreSQL's ``ON CONFLICT DO UPDATE`` refuses a batch with duplicate
        conflict targets, so this would fail as a 500 further down. Rejecting it
        here also makes the ambiguity explicit: with two rows for one SKU, "which
        cost did I save?" has no defensible answer.
        """
        seen = {item.nm_id for item in items}
        if len(seen) != len(items):
            raise ValueError("Each nm_id may appear only once in a batch.")
        return items


class CostPriceSaveResponse(BaseModel):
    """Outcome of a bulk save."""

    saved: int


class CostPriceImportIssue(BaseModel):
    """One row of an uploaded workbook the import could not apply.

    Only rows that *looked* intended and failed are reported — a blank cost is
    the norm for an uncosted SKU and is skipped without an issue. Each carries
    the sheet row so the seller can find and fix the offending line.
    """

    row: int
    nm_id: int | None = None
    reason: str


class CostPriceImportResponse(BaseModel):
    """Outcome of an XLSX cost-price import.

    ``applied`` costs were written; ``skipped`` rows were not (a blank cost, an
    unknown SKU, or a value the validator rejected). ``issues`` explains every
    skip that was not simply an empty cell, so a partial import is never silent.
    """

    applied: int
    skipped: int
    issues: list[CostPriceImportIssue] = Field(default_factory=list)
