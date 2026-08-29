"""What an organisation has paid for, and what happens when it lapses.

One row per organisation, created when its activation code is redeemed. Payment
itself happens outside this system — we are handed money and hand back a code —
so this table records the *consequence* of a payment, never the payment.

**Expiry is a ramp, not a cliff.** Three states, in order:

``active``
    ``now < expires_at``. Everything works.
``grace``
    ``expires_at <= now < expires_at + grace_days``. Everything still works and
    the UI says the subscription has lapsed. This period exists because the
    renewal is a manual bank transfer between two humans in two countries, and
    the failure it prevents — a seller locked out of their own numbers on the
    morning the payment is still clearing — is far worse than a few extra days
    of access.
``read_only``
    Past the grace period. Every read still answers; every write and every WB
    refresh is refused. Deliberately not a full block: the data is the
    customer's own, locking them out of it is a hostage position rather than a
    payment incentive, and a customer who can still see what they are missing
    is the one who renews.

The limits are nullable and ``NULL`` means unlimited, which is what every
organisation gets today. They exist as columns now because retrofitting a quota
onto live tenants is the kind of change that needs a migration, a backfill and a
conversation with every customer at once; a column that is always ``NULL`` costs
nothing and turns that into a single ``UPDATE``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.ids import uuid7

#: Every table in this module lives in the ``organizations`` logical schema.
_SCHEMA: str = "organizations"

#: How long a redeemed activation code buys. The base term, in days.
DEFAULT_SUBSCRIPTION_DAYS: int = 30


class Subscription(Base):
    """One organisation's access term.

    Attributes:
        id: UUIDv7 primary key.
        organization_id: The organisation this governs (FK, UNIQUE, cascade
            delete). One row per organisation: a second one would make "is this
            company paid up?" a question with two answers.
        started_at: When the term began (the activation, or the last renewal).
        expires_at: When it ends. The ramp above starts here.
        grace_days: How long full access survives past ``expires_at``. A column
            rather than a constant so a specific customer can be given more
            without a deploy — the default comes from settings.
        max_workspaces: Cap on the organisation's workspaces; ``NULL`` =
            unlimited.
        max_managers: Cap on managers (the owner is never counted, since an
            organisation cannot exist without one); ``NULL`` = unlimited.
        created_at: Row creation timestamp (UTC).
        updated_at: Last renewal or limit change (UTC).
    """

    __tablename__ = "subscriptions"
    __table_args__ = {"schema": _SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.organizations.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    grace_days: Mapped[int] = mapped_column(Integer, nullable=False)
    #: NULL = unlimited (see the module docstring).
    max_workspaces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: NULL = unlimited.
    max_managers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
