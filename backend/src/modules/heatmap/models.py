"""The heatmap's own tables: seller-defined groups of articles, and their norms.

Everything else the heatmap shows belongs to other modules and is read through
their contracts; what it owns is what a seller types into it — the "Groups"
("spandex_two_piece" as five colour variants of one product, read as one row) and
the hand-set norm an article's cells are painted against.

Every table carries ``workspace_id``, the membership table included. The group id
alone would scope a member row transitively, but row-level security can only
police a column the row itself carries, and a table without one is the kind the
diagnostic gate cannot fence either. A few bytes per row buys a policy.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Double,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.ids import uuid7

_SCHEMA: str = "heatmap"

#: Longest group name the page accepts; the schema's ``max_length`` matches it.
GROUP_NAME_MAX_LENGTH: int = 80


class SkuGroup(Base):
    """A named set of one workspace's articles.

    Attributes:
        id: UUIDv7 — time-ordered, and not an enumeration oracle.
        workspace_id: Owning workspace; the group is shared by everyone in it.
        name: What the seller called it; unique within the workspace, so the
            filter never lists two options that read the same.
        created_at: When it was made.
    """

    __tablename__ = "sku_group"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_heatmap_sku_group_workspace_name"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.workspaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(GROUP_NAME_MAX_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SkuGroupItem(Base):
    """One article's membership in one group.

    Attributes:
        group_id: The group; deleting it deletes its members.
        nm_id: The article (proved to be the workspace's own before it is written).
        workspace_id: The group's workspace, repeated so the row can carry a policy.
    """

    __tablename__ = "sku_group_item"
    __table_args__ = {"schema": _SCHEMA}

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.sku_group.id", ondelete="CASCADE"), primary_key=True
    )
    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.workspaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )


class SkuNorm(Base):
    """A seller's own norm for one article on one metric.

    What "Target: manual" paints the article's cells against instead of the
    median of its days. Per day, in the metric's own unit — the page scales it
    to a week or a month for the metrics that add up.

    Attributes:
        id: UUIDv7.
        workspace_id: Owning workspace; the norm is shared by everyone in it.
        nm_id: The article (proved to be the workspace's own before it is written).
        metric: A :data:`~src.modules.heatmap.schemas.MetricKey`.
        value: The norm.
        updated_at: When it was last set.
    """

    __tablename__ = "sku_norm"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "nm_id", "metric", name="uq_heatmap_sku_norm_workspace_nm_metric"
        ),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.workspaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[float] = mapped_column(Double, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
