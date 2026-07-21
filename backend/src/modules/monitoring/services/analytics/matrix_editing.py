"""The matrix spreadsheet-editing flows: preview one edit, persist a working copy."""

from __future__ import annotations

from datetime import date

from src.modules.monitoring.repos import MatrixOverrideRepository
from src.modules.monitoring.schemas import SkuDetailResponse
from src.modules.monitoring.schemas.matrix import (
    MatrixBaseState,
    MatrixCellEdit,
    MatrixPreviewResponse,
)
from src.modules.monitoring.services.analytics.detail import DetailAnalytics, derive_fact_base
from src.modules.monitoring.services.analytics.window import resolve_window
from src.modules.monitoring.services.matrix import (
    apply_edit,
    build_matrix_from_base,
    diff_to_overrides,
)


class MatrixEditingAnalytics:
    """Recomputes matrix previews and persists manual edits as overrides."""

    def __init__(
        self,
        *,
        detail: DetailAnalytics,
        matrix_override_repo: MatrixOverrideRepository,
    ) -> None:
        """Inject the detail read service (shared fact fetch) and the override store."""
        self._detail = detail
        self._matrix_overrides = matrix_override_repo

    def preview_matrix_edit(
        self, base: MatrixBaseState, edit: MatrixCellEdit, *, nm_id: int | None = None
    ) -> MatrixPreviewResponse:
        """Apply one pending cell-edit to a working copy and recompute (no I/O).

        Pure recomputation: the client holds the working copy, this resolves the
        edit into its inputs and re-derives the display matrix. Nothing is
        persisted — that is what :meth:`save_matrix` does.

        Args:
            base: The client's current input working copy.
            edit: The cell the user just changed.
            nm_id: The SKU on screen — an edit to an ad zone's carts/orders
                moves that SKU's row of the associative breakdown with it.

        Returns:
            The recomputed working copy and display matrix.

        Raises:
            ValidationError: If the edit targets a read-only / non-invertible cell.
        """
        new_base = apply_edit(base, edit, viewed_nm_id=nm_id)
        return MatrixPreviewResponse(base=new_base, matrix=build_matrix_from_base(new_base))

    async def save_matrix(
        self,
        *,
        nm_id: int,
        base: MatrixBaseState,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> SkuDetailResponse:
        """Persist a working copy as overrides, then return the refreshed detail.

        The working copy is diffed against a freshly fact-derived base; only the
        input cells that actually changed are stored (a cell edited back to its
        harvested value drops its override). Existing overrides for the window
        are replaced in one transaction.

        Args:
            nm_id: WB SKU identifier.
            base: The working copy to persist.
            date_from: Optional inclusive window start (defaults applied here).
            date_to: Optional inclusive window end (defaults applied here).

        Returns:
            The detail view rebuilt with the saved overrides applied.
        """
        date_from, date_to = resolve_window(date_from, date_to)
        inputs = await self._detail.fetch_matrix_inputs(
            nm_id=nm_id, date_from=date_from, date_to=date_to
        )
        fact_base = derive_fact_base(inputs, nm_id=nm_id, date_from=date_from, date_to=date_to)
        rows = diff_to_overrides(nm_id=nm_id, working=base, fact=fact_base)
        await self._matrix_overrides.replace_window(
            nm_id=nm_id, date_from=date_from, date_to=date_to, rows=rows
        )
        return await self._detail.get_detail(nm_id=nm_id, date_from=date_from, date_to=date_to)
