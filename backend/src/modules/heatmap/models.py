"""The heatmap's own tables: seller-defined groups of articles.

Everything else the heatmap shows belongs to other modules and is read through
their contracts; the one thing it owns is the «Группы» a seller assembles for
it — «спандекс_двойка» as five colour variants of one product, read as one row.

Both tables carry ``workspace_id``, the membership table included. The group id
alone would scope a member row transitively, but row-level security can only
police a column the row itself carries, and a table without one is the kind the
diagnostic gate cannot fence either. A few bytes per row buys a policy.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.ids import uuid7

_SCHEMA: str = "heatmap"

#: Longest group name the page accepts; the schema's ``max_length`` matches it.
GROUP_NAME_MAX_LENGTH: int = 80


class SkuGroup(Base):
    """A named set of one кабинет's articles.

    Attributes:
        id: UUIDv7 — time-ordered, and not an enumeration oracle.
        workspace_id: Owning кабинет; the group is shared by everyone in it.
        name: What the seller called it; unique within the кабинет, so the
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
        nm_id: The article (proved to be the кабинет's own before it is written).
        workspace_id: The group's кабинет, repeated so the row can carry a policy.
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
