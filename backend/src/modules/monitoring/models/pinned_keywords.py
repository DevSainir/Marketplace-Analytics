"""Pinned search-phrase model — «Закрепить» on the live-position search box.

A pin is a standing question: "where does this SKU rank for this phrase". It
exists because the probe answers only for the moment it runs, and a seller
watching a bid wants yesterday's number next to today's without retyping the
phrase three times a day.

Pins are GLOBAL, the same convention as
:class:`~src.modules.monitoring.models.pinned_skus.PinnedSku` and
:class:`~src.modules.monitoring.models.sku_day_comment.SkuDayComment`: the
natural key is ``(nm_id, keyword)`` and the row carries no user reference.
Tenancy needs no column either — ``nm_id`` already belongs to exactly one
workspace through :class:`~src.modules.monitoring.models.products.ProductCard`,
which every route and the refresh task join through.

**The last result lives on the pin, not in a history table.** A position is a
sample for one region at one moment (see the search client's module docstring),
and WB serves no history to reconcile it against — so a rank older than the last
check is not a fact anyone can defend. The card shows the newest number and when
it was taken; nothing accumulates. If this ever needs a trend line, that is a new
time-series table keyed by ``(nm_id, keyword, date)``, not a widening of this one.

``last_checked_at IS NULL`` means the pin has never been probed. That is NOT the
same as ``last_position IS NULL`` with a timestamp set, which means WB answered
and the SKU was not inside the scanned depth — opposite conclusions for a seller
deciding whether to bid, so the two states stay distinguishable.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"

#: Longest phrase a pin may hold. Mirrors ``KEYWORD_MAX_LENGTH`` in the cluster
#: analytics service — the probe rejects anything longer, so a pin that could
#: hold more would be a pin that can never be checked.
KEYWORD_MAX_LENGTH: int = 100


class PinnedKeyword(Base):
    """One SKU's pinned search phrase and its latest known position.

    Attributes:
        nm_id: WB SKU identifier the phrase is pinned to.
        keyword: The phrase as the seller typed it (the probe normalizes
            separately — see ``normalized_query``).
        normalized_query: WB's own normalization of the phrase from the last
            probe («носки мужские» → «мужские носки»), or ``""`` before the
            first check. Stored because it is the key the advertising cluster
            rows carry, which is what lets a pinned phrase be lined up against
            the campaign's clusters.
        last_position: 1-based rank at the last check, or ``None`` for "checked,
            not found within the scanned depth" (and also before any check —
            ``last_checked_at`` is what separates them).
        last_positions_scanned: How deep that check actually looked, so the UI
            can say «не найден в первых N» with a real N rather than implying
            the whole catalogue was searched.
        last_total_found: WB's own result count for the phrase at that moment —
            the competition the rank is measured against.
        last_truncated: WB had results deeper than the probe looked, so absence
            means "not in the scanned depth", never "not in WB search".
        last_checked_at: When the phrase was last probed; ``None`` until the
            first check.
        created_at: When the phrase was pinned — the pin order in the UI.
    """

    __tablename__ = "pinned_keyword"
    __table_args__ = {"schema": _SCHEMA}

    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    keyword: Mapped[str] = mapped_column(String(KEYWORD_MAX_LENGTH), primary_key=True)

    normalized_query: Mapped[str] = mapped_column(
        String(KEYWORD_MAX_LENGTH), nullable=False, server_default=""
    )

    last_position: Mapped[int | None] = mapped_column(Integer, nullable=True)

    last_positions_scanned: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    last_total_found: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    last_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
