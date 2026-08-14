"""«Баланс по товарным остаткам» — what the unsold stock is worth, by warehouse.

The P&L answers what the goods that MOVED did to the seller's money. This answers
the other half: how much money is still lying in WB's warehouses, and where. Both
sides of the balance come from figures the module already owns — monitoring's
daily stock snapshot for the units, the seller's own cost prices for the money —
so the table introduces no new arithmetic beyond ``units x cost``.

Split into a pure builder and a thin service: the builder is where the pricing,
the row order and the caveats live, and it is a plain function over plain
mappings, so its behaviour is pinned by unit tests without a database anywhere
near it. The totals are NOT here — see :mod:`~.schemas.balance` for why they
belong to the client that draws them.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from src.modules.finreports.models import BalancePinKind
from src.modules.finreports.repos import (
    BalancePinRepository,
    CostPriceRepository,
    PnlRepository,
)
from src.modules.finreports.schemas.balance import (
    BalanceCell,
    BalanceResponse,
    BalanceSkuRow,
)
from src.modules.monitoring.contract import WarehouseStock

_ZERO = Decimal(0)

#: Currency assumed when the workspace has no settlement rows to read one off.
#: The same fallback the P&L uses, for the same reason: the cost prices this
#: seller enters are in it, and a balance is worth more than a blank screen.
_FALLBACK_CURRENCY = "KGS"


def build_balance(
    *,
    stat_date: date,
    stock: dict[tuple[int, str], WarehouseStock],
    costs: dict[int, Decimal],
    identity: dict[int, tuple[str, str, str]],
    vendor_codes: dict[int, str],
    pinned_skus: set[int],
    pinned_warehouses: set[str],
    uncounted_warehouses: set[str],
    uncounted_skus: set[int],
    currency: str,
    span: tuple[date | None, date | None],
) -> BalanceResponse:
    """Assemble the SKU x warehouse grid for one snapshot day.

    Args:
        stat_date: The snapshot day being rendered.
        stock: ``{(nm_id, warehouse): units}`` — only cells that hold or move
            something.
        costs: ``{nm_id: cost per unit}`` in ``currency``; SKUs absent from it
            are uncosted and get quantities but no money.
        identity: ``{nm_id: (sa_name, subject, brand)}`` from the settlement rows.
        vendor_codes: ``{nm_id: vendor_code}`` — the name fallback for a SKU that
            holds stock but has never settled a row.
        pinned_skus: SKUs the seller pinned to the top of the grid.
        pinned_warehouses: Warehouses pinned to the left of the grid.
        uncounted_warehouses: Warehouses marked «Не считать» — priced like any
            other, but never ranked on and never totalled.
        uncounted_skus: SKUs marked «Не считать» — the same on the row axis.
        currency: Settlement currency every money figure is stated in.
        span: ``(first, last)`` snapshot day on record, for the day picker.

    Returns:
        The priced grid, the marks on it, and the caveats that qualify it.
    """
    rows = _build_rows(
        stock=stock,
        costs=costs,
        identity=identity,
        vendor_codes=vendor_codes,
        uncounted_warehouses=uncounted_warehouses,
    )
    uncosted = [row for row in rows if row.cost_price is None]
    return BalanceResponse(
        stat_date=stat_date,
        available_from=span[0],
        available_to=span[1],
        currency=currency,
        rows=rows,
        pinned_skus=sorted(pinned_skus),
        pinned_warehouses=sorted(pinned_warehouses),
        uncounted_warehouses=sorted(uncounted_warehouses),
        uncounted_skus=sorted(uncounted_skus),
        uncosted_count=len(uncosted),
        notes=_notes(stat_date=stat_date, rows=rows, uncosted=uncosted, span=span),
    )


def _build_rows(
    *,
    stock: dict[tuple[int, str], WarehouseStock],
    costs: dict[int, Decimal],
    identity: dict[int, tuple[str, str, str]],
    vendor_codes: dict[int, str],
    uncounted_warehouses: set[str],
) -> list[BalanceSkuRow]:
    """One row per SKU holding stock, largest counted balance first."""
    by_sku: dict[int, list[tuple[str, WarehouseStock]]] = {}
    for (nm_id, warehouse), units in stock.items():
        by_sku.setdefault(nm_id, []).append((warehouse, units))

    rows: list[BalanceSkuRow] = []
    ranking: dict[int, tuple[Decimal, int]] = {}
    for nm_id, cells in by_sku.items():
        cost = costs.get(nm_id)
        sa_name, subject, brand = identity.get(nm_id, ("", "", ""))
        rows.append(
            BalanceSkuRow(
                nm_id=nm_id,
                # A SKU with stock but no settlement history has no name in the
                # финотчёт; the catalogue vendor code names it, and only a SKU
                # missing from both falls back to its bare nm_id.
                sa_name=sa_name or vendor_codes.get(nm_id) or str(nm_id),
                subject_name=subject,
                brand_name=brand,
                cost_price=cost,
                cells=[
                    BalanceCell(
                        warehouse_name=warehouse,
                        quantity=units.quantity,
                        in_way=units.in_way,
                        balance=None if cost is None else cost * units.quantity,
                        in_way_balance=None if cost is None else cost * units.in_way,
                    )
                    for warehouse, units in sorted(cells)
                ],
            )
        )
        # Rank on the COUNTED stock only, so a warehouse the seller took out of
        # the totals cannot decide which rows they see first either. Goods in
        # transit are ranked WITH the stock: they are the same money, and a SKU
        # whose whole holding happens to be riding to buyers today would
        # otherwise sink to the bottom of the table on the day it matters most.
        counted = [units for warehouse, units in cells if warehouse not in uncounted_warehouses]
        held = sum(units.quantity + units.in_way for units in counted)
        ranking[nm_id] = (_ZERO if cost is None else cost * held, held)

    # Money first — the row worth 600 000 matters more than the row of 600 units
    # of a cheap SKU. Uncosted rows have no balance to rank on and fall to the
    # bottom, where the «без себестоимости» caveat expects them.
    rows.sort(key=lambda row: (-ranking[row.nm_id][0], -ranking[row.nm_id][1], row.sa_name))
    return rows


def _notes(
    *,
    stat_date: date,
    rows: list[BalanceSkuRow],
    uncosted: list[BalanceSkuRow],
    span: tuple[date | None, date | None],
) -> list[str]:
    """The caveats that decide how the bottom-right corner should be read."""
    notes: list[str] = []
    if not rows:
        first, last = span
        if first is None:
            notes.append("Остатки ещё не собраны — по этому кабинету нет ни одного снимка склада.")
        else:
            notes.append(
                f"За {stat_date.isoformat()} нет снимка остатков "
                f"(есть с {first.isoformat()} по {last.isoformat() if last else '—'}). "
                "Остатки не переносятся с соседнего дня — выберите день со снимком."
            )
        return notes

    if uncosted:
        worst = ", ".join(row.sa_name for row in uncosted[:5])
        notes.append(
            f"Без себестоимости {len(uncosted)} SKU с остатками (крупнейшие: {worst}) — "
            "их баланс не посчитан и в «Итого» не входит. Заполните в разделе «Себестоимость»."
        )
    notes.append(
        "Баланс — остаток, умноженный на себестоимость единицы: сколько денег лежит "
        "на складе, а не сколько за него выручат. Товар в пути (к клиенту и от него) "
        "показан отдельной колонкой «В пути», но в «По себестоимости» входит — он уже "
        "оплачен и вернётся на склад или будет выкуплен."
    )
    return notes


class BalanceService:
    """Builds the stock-balance grid for a workspace and one snapshot day."""

    def __init__(
        self,
        *,
        pnl_repo: PnlRepository,
        cost_repo: CostPriceRepository,
        pin_repo: BalancePinRepository,
    ) -> None:
        """Wire the read service from its repositories."""
        self._pnl = pnl_repo
        self._costs = cost_repo
        self._pins = pin_repo

    async def get_balance(
        self,
        *,
        workspace_id: uuid.UUID,
        stat_date: date,
        stock: dict[tuple[int, str], WarehouseStock],
        vendor_codes: dict[int, str],
        span: tuple[date | None, date | None],
    ) -> BalanceResponse:
        """Return the grid for one snapshot day.

        The stock itself belongs to the monitoring module and is handed in by
        the router, which resolves it through that module's contract — the same
        pattern the per-SKU P&L uses for orders and advertising.

        Args:
            workspace_id: Owning workspace.
            stat_date: The snapshot day to render.
            stock: ``{(nm_id, warehouse): units}`` for that day, in-transit
                included.
            vendor_codes: Catalogue names, the identity fallback.
            span: ``(first, last)`` snapshot day on record.

        Returns:
            The priced grid, its marks and its caveats.
        """
        currency = await self._pnl.settlement_currency(workspace_id=workspace_id)
        nm_ids = {nm_id for nm_id, _warehouse in stock}
        return build_balance(
            stat_date=stat_date,
            stock=stock,
            costs=await self._costs.costs_by_nm_id(
                workspace_id=workspace_id, currency=currency or _FALLBACK_CURRENCY
            ),
            identity=await self._pnl.sku_identity(workspace_id=workspace_id, nm_ids=nm_ids),
            vendor_codes=vendor_codes,
            pinned_skus=await self._sku_marks(workspace_id, BalancePinKind.SKU),
            pinned_warehouses=await self._pins.list_values(
                workspace_id=workspace_id, kind=BalancePinKind.WAREHOUSE
            ),
            uncounted_warehouses=await self._pins.list_values(
                workspace_id=workspace_id, kind=BalancePinKind.WAREHOUSE_UNCOUNTED
            ),
            uncounted_skus=await self._sku_marks(workspace_id, BalancePinKind.SKU_UNCOUNTED),
            currency=currency or _FALLBACK_CURRENCY,
            span=span,
        )

    async def set_pin(
        self, *, workspace_id: uuid.UUID, kind: BalancePinKind, value: str, pinned: bool
    ) -> None:
        """Set or clear one mark on the grid. Idempotent both ways."""
        await self._pins.set_pinned(
            workspace_id=workspace_id, kind=kind, value=value, pinned=pinned
        )

    async def _sku_marks(self, workspace_id: uuid.UUID, kind: BalancePinKind) -> set[int]:
        """One kind of SKU mark as ``nm_id``s, ignoring any value that is not one.

        Marks are stored as text so one table serves rows and columns alike; a
        value that is not a number can only come from a hand-edited row, and
        dropping it is better than failing the whole grid over it.
        """
        values = await self._pins.list_values(workspace_id=workspace_id, kind=kind)
        return {int(value) for value in values if value.lstrip("-").isdigit()}
