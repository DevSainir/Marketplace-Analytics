"""Manual matrix-cell override model.

Managers edit the daily metrics matrix like a spreadsheet. Their edits are
resolved to **input** facts (see :mod:`services.matrix_edit`) and persisted here
as a thin layer *over* the pristine WB fact tables — the raw harvested numbers
are never overwritten. On read the overlay is applied before the matrix is
derived; any WB refresh (nightly harvest or a manual «Обновить») clears a SKU's
overrides, so this layer is intentionally short-lived.

One row per overridden cell: ``(nm_id, stat_date, bucket, field)``. Two kinds:

* **Input override** — ``bucket`` is an advertising bucket or ``"funnel"`` and
  ``field`` is an input name (``views``, ``open_count``, …). Applied to the
  base BEFORE the matrix is derived, so dependent cells recompute (dynamic).
* **Display override** — ``bucket == "cell"`` and ``field`` is the target
  cell's ``"<bucket>:<metric>"`` (e.g. ``"total:order_sum"``). Applied AFTER
  the formulas, so any non-invertible cell (a derived rollup, the empty
  «Каталог» zone, a tainted split) is still editable — shown verbatim.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class MatrixOverride(Base):
    """One manually edited input fact for the daily metrics matrix.

    Attributes:
        nm_id: WB SKU identifier.
        stat_date: The day column the override applies to.
        bucket: An advertising bucket / ``funnel`` (input override) or ``cell``
            (display override — see the module docstring).
        field: The input field name (``views``, ``open_count``, …) for an input
            override, or the ``"<bucket>:<metric>"`` cell key for a display one.
        value: The manager's value; integer counts are stored with a zero
            fractional part.
        updated_at: When the override was last written.
    """

    __tablename__ = "matrix_override"
    __table_args__ = {"schema": _SCHEMA}

    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    bucket: Mapped[str] = mapped_column(String(16), primary_key=True)
    # Wide enough for a ``"<bucket>:<metric>"`` display-override key
    # (e.g. ``"manual_catalog:order_conversion"``).
    field: Mapped[str] = mapped_column(String(48), primary_key=True)

    value: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
