"""Read/write service for the seller's per-SKU cost prices.

The module's only write path. It exists to keep two things honest:

* **Uncosted SKUs are surfaced, not hidden.** Listing costs alone would let a
  seller believe the P&L is complete when 85 % of the units it settled have no
  cost on file. The listing therefore also returns every SKU that has sold but
  carries no cost, ordered by units so the expensive omissions come first.
* **Costs entered in the wrong currency are rejected, never converted.** The
  settlement is KGS; a cost typed in RUB would silently produce a plausible,
  wrong margin.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError as PydanticValidationError

from src.core.config import settings
from src.core.exceptions import ValidationError
from src.core.timeutils import moscow_today
from src.modules.finreports.repos import CostPriceRepository, PnlRepository, SkuUnits
from src.modules.finreports.schemas.cost_price import (
    CostPriceImportIssue,
    CostPriceImportResponse,
    CostPriceInput,
    CostPriceItem,
    CostPriceListResponse,
    CostPriceSaveResponse,
)
from src.modules.finreports.services.cost_upload_parser import ParsedCostRow, parse_cost_upload

#: How far back the "which SKUs still need a cost" list looks. Long enough to
#: cover seasonality, short enough that a card retired two years ago does not
#: nag forever.
_COVERAGE_WINDOW_DAYS = 365


class CostPriceService:
    """Manages the seller-entered cost of goods."""

    def __init__(self, *, cost_repo: CostPriceRepository, pnl_repo: PnlRepository) -> None:
        """Wire the service from the cost and settlement repositories."""
        self._costs = cost_repo
        self._pnl = pnl_repo

    async def list_cost_prices(self, *, workspace_id: uuid.UUID) -> CostPriceListResponse:
        """Return every cost on file plus the SKUs that still need one.

        Args:
            workspace_id: Owning workspace.

        Returns:
            Costed SKUs by ``nm_id``, and uncosted-but-selling SKUs by volume.
        """
        stored = await self._costs.list_for_workspace(workspace_id)
        by_nm = {row.nm_id: row for row in stored}
        today = moscow_today()
        sold = await self._pnl.sku_units(
            workspace_id=workspace_id,
            date_from=today - timedelta(days=_COVERAGE_WINDOW_DAYS),
            date_to=today,
        )
        units_by_nm = {s.nm_id: s for s in sold}

        items = [
            CostPriceItem(
                nm_id=row.nm_id,
                cost=row.cost,
                currency=row.currency,
                vendor_code=row.vendor_code
                or (units_by_nm[row.nm_id].vendor_code if row.nm_id in units_by_nm else ""),
                source=row.source,
                note=row.note,
                updated_at=row.updated_at,
                sold_units=self._net_units(units_by_nm.get(row.nm_id)),
            )
            for row in stored
        ]
        missing = [
            CostPriceItem(
                nm_id=s.nm_id,
                cost=0,
                currency="",
                vendor_code=s.vendor_code,
                source="",
                note="",
                sold_units=self._net_units(s),
            )
            for s in sold
            if s.nm_id not in by_nm
        ]
        currency = next((row.currency for row in stored), "KGS")
        return CostPriceListResponse(currency=currency, items=items, missing=missing)

    async def save_cost_prices(
        self, *, workspace_id: uuid.UUID, items: list[CostPriceInput]
    ) -> CostPriceSaveResponse:
        """Insert or overwrite a batch of cost prices.

        Args:
            workspace_id: Owning workspace.
            items: The costs to persist (validated by the schema).

        Returns:
            How many rows were written.

        Raises:
            ValidationError: If the batch would take the workspace past its
                cost-row bound (register P1.13).
        """
        await self._refuse_if_over_quota(workspace_id=workspace_id, items=items)
        saved = await self._costs.upsert_many(
            [
                {
                    "workspace_id": workspace_id,
                    "nm_id": item.nm_id,
                    "cost": item.cost,
                    "currency": item.currency,
                    "vendor_code": item.vendor_code,
                    "source": "manual",
                    "note": item.note,
                }
                for item in items
            ]
        )
        return CostPriceSaveResponse(saved=saved)

    async def _refuse_if_over_quota(
        self, *, workspace_id: uuid.UUID, items: list[CostPriceInput]
    ) -> None:
        """Refuse a batch that would take the workspace past its row bound.

        Counts what the batch would ADD, not what it touches: re-entering a
        cost for a SKU already on file consumes no new storage, and treating it
        as new would refuse a customer re-uploading their own catalogue — the
        single most likely legitimate use of this endpoint.

        Args:
            workspace_id: Owning workspace.
            items: The incoming batch.

        Raises:
            ValidationError: When the bound would be exceeded.
        """
        cap = settings.max_cost_price_rows_per_workspace
        incoming = {item.nm_id for item in items}
        stored = await self._costs.count_for_workspace(workspace_id)
        if stored + len(incoming) <= cap:
            # The common case costs one COUNT: if even treating every incoming
            # SKU as new stays under the bound, the second query is pointless.
            return
        already = await self._costs.count_existing(workspace_id=workspace_id, nm_ids=list(incoming))
        if stored + (len(incoming) - already) <= cap:
            return
        raise ValidationError(
            f"Достигнут лимит себестоимостей ({cap} артикулов на кабинет). "
            "Удалите ненужные строки или обратитесь в поддержку."
        )

    async def delete_cost_price(self, *, workspace_id: uuid.UUID, nm_id: int) -> int:
        """Remove one SKU's cost price.

        Args:
            workspace_id: Owning workspace.
            nm_id: The SKU to clear.

        Returns:
            ``1`` when a row was removed, ``0`` when there was nothing on file.
        """
        return await self._costs.delete_one(workspace_id=workspace_id, nm_id=nm_id)

    async def import_workbook(
        self, *, workspace_id: uuid.UUID, filename: str, data: bytes
    ) -> CostPriceImportResponse:
        """Apply the «Себестоимость» column of an uploaded cost sheet.

        The round trip's write half: parse the file (``.xlsx``, ``.xls`` or
        ``.csv``), and for every row carrying a cost, write it against the SKU
        named by its «Артикул WB» (``nm_id``). The guarantees that keep a
        hand-edited spreadsheet from poisoning the P&L:

        * **Only SKUs the workspace already knows are touched.** An ``nm_id`` the
          export never listed (a typo, a paste from another seller's file) is
          reported, never inserted — a cost for a SKU that does not settle here
          is meaningless and would sit in the table forever.
        * **The cost currency is the workspace's, not the file's.** Costs are
          stored in the settlement currency the P&L reconciles against, so a
          value cannot be silently admitted in the wrong one (PNL.md §13).
        * **Blank costs change nothing.** A downloaded file is mostly empty
          «Себестоимость» cells; leaving one empty means "no cost yet", not
          "clear the cost", so blanks are skipped, never deletions.

        Args:
            workspace_id: Owning workspace — the only one written to.
            filename: The upload's name, used to pick the format reader.
            data: The uploaded file bytes (``.xlsx``, ``.xls`` or ``.csv``).

        Returns:
            How many costs were applied, how many rows were skipped, and why
            each non-blank skip happened.

        Raises:
            ValidationError: The upload is not a readable cost sheet (propagated
                from the parser).
        """
        parsed = parse_cost_upload(filename, data)
        listing = await self.list_cost_prices(workspace_id=workspace_id)
        known = {item.nm_id for item in listing.items} | {item.nm_id for item in listing.missing}
        vendor_by_nm = {
            item.nm_id: item.vendor_code
            for item in (*listing.items, *listing.missing)
            if item.vendor_code
        }
        currency = listing.currency

        issues: list[CostPriceImportIssue] = []
        by_nm: dict[int, dict[str, object]] = {}
        skipped = 0
        for entry in parsed:
            outcome = self._row_to_cost(
                entry, known=known, currency=currency, vendor_by_nm=vendor_by_nm
            )
            if outcome is None:  # A blank cost: the expected empty row, not an error.
                skipped += 1
                continue
            if isinstance(outcome, CostPriceImportIssue):
                issues.append(outcome)
                skipped += 1
                continue
            nm_id, values = outcome
            # A duplicated nm_id would blow up the ON CONFLICT batch; the last
            # occurrence wins and the earlier one is reported rather than dropped
            # in silence, so "which cost did I upload?" always has an answer.
            if nm_id in by_nm:
                issues.append(
                    CostPriceImportIssue(
                        row=entry.row, nm_id=nm_id, reason="Артикул встречается в файле дважды."
                    )
                )
            by_nm[nm_id] = values

        rows = [{"workspace_id": workspace_id, **values} for values in by_nm.values()]
        applied = await self._costs.upsert_many(rows)
        return CostPriceImportResponse(applied=applied, skipped=skipped, issues=issues)

    def _row_to_cost(
        self,
        entry: ParsedCostRow,
        *,
        known: set[int],
        currency: str,
        vendor_by_nm: dict[int, str],
    ) -> CostPriceImportIssue | tuple[int, dict[str, object]] | None:
        """Turn one parsed row into an upsert mapping, an issue, or a skip.

        Returns ``None`` for a blank cost (a silent skip), a
        :class:`CostPriceImportIssue` for a row that meant to carry a cost but
        could not, or ``(nm_id, values)`` ready for :meth:`upsert_many`.
        """
        nm_id = self._coerce_nm_id(entry.nm_id_raw)
        if nm_id is None:
            return CostPriceImportIssue(row=entry.row, reason="Неверный nm_id.")
        cost = self._coerce_cost(entry.cost_raw)
        if cost is None:
            return None  # Empty «Себестоимость» — nothing to do for this SKU.
        if isinstance(cost, str):  # A non-numeric cell; `cost` carries the reason.
            return CostPriceImportIssue(row=entry.row, nm_id=nm_id, reason=cost)
        if nm_id not in known:
            return CostPriceImportIssue(
                row=entry.row, nm_id=nm_id, reason="SKU не продавался в этом кабинете."
            )
        try:
            validated = CostPriceInput(
                nm_id=nm_id, cost=cost, currency=currency, vendor_code=vendor_by_nm.get(nm_id, "")
            )
        except PydanticValidationError:
            return CostPriceImportIssue(
                row=entry.row, nm_id=nm_id, reason="Недопустимая себестоимость."
            )
        return nm_id, {
            "nm_id": validated.nm_id,
            "cost": validated.cost,
            "currency": validated.currency,
            "vendor_code": validated.vendor_code,
            "source": "manual",
            "note": validated.note,
        }

    @staticmethod
    def _coerce_nm_id(raw: object) -> int | None:
        """Read an ``nm_id`` cell, which Excel may hand back as a float or text."""
        if isinstance(raw, bool):  # bool is an int subclass — never a SKU id.
            return None
        try:
            value = int(raw)  # type: ignore[call-overload]  # str/float/int all valid here.
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    @staticmethod
    def _coerce_cost(raw: object) -> Decimal | str | None:
        """Read a «Себестоимость» cell.

        Returns ``None`` for an empty cell, a :class:`Decimal` for a number, or a
        human-readable reason string when the cell is present but not a number.
        """
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            return None
        if isinstance(raw, bool):
            return "Себестоимость не является числом."
        text = str(raw).strip().replace(",", ".").replace(" ", "")
        try:
            return Decimal(text)
        except InvalidOperation:
            return "Себестоимость не является числом."

    @staticmethod
    def _net_units(units: SkuUnits | None) -> int:
        """Net settled units for a SKU (0 when it has not sold in the window)."""
        if units is None:
            return 0
        return units.sold_units - units.returned_units


__all__ = ["CostPriceService"]
