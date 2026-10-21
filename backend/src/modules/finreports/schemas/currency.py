"""Response DTO for the workspace's settlement currency."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SettlementCurrencyResponse(BaseModel):
    """The currency every money figure of the active workspace is stated in.

    One seller account is priced, advertised and paid in one currency, so the
    code WB settles it in is also the unit of its funnel sums, its prices and
    its advertising spend — which is why pages that never show a settlement
    figure still ask for it.
    """

    currency: str = Field(
        description="ISO 4217 code WB settles this кабинет in (e.g. `KGS`); empty "
        "before the first settlement report, when the unit is not yet known."
    )
