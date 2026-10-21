"""Which advertising campaigns a test's traffic came from, and what they are.

A card can be pushed by more than one campaign at once, and the counters of all
of them used to be added together before anything was recorded — so a photo's
running tally held the sum and no later question could take it apart. The split is
now made where the numbers arrive (see :mod:`..services.collection`), and every
row that carries traffic carries the campaign id it came from.

That leaves one thing the counters cannot say: **what the campaign was**. WB's
``/api/advert/v2/adverts`` names it — «Единая ставка», «Руч. поиск», «Руч.
полки» or «CPC» — and answers only for campaigns it still lists. A campaign
archived mid-test disappears from that listing while its measurements stay on
the page forever, so the name and the kind are copied into this table on every
pass that sees the campaign rather than looked up when the page is rendered.

Deliberately NOT read from ``monitoring.campaigns``, which holds the same facts
for the whole account: that dimension is filled by the nightly harvest, and a
campaign started this morning — the common case for a test, since a seller
starts one to run the test — is not in it. See :mod:`..services.campaigns`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "ab_tests"


class AbTestCampaign(Base):
    """One advertising campaign that has served a test's card.

    Attributes:
        test_id: Owning test (composite PK).
        campaign_id: WB ``advertId`` (composite PK). ``0`` is the **legacy**
            row: windows recorded before the split carry it, and they are the
            sum of every campaign that was running at the time. It cannot be
            taken apart retroactively — the source rows were added together
            before they were stored — so it is presented as one nameless
            campaign rather than pretended away.
        name: The campaign's own name in the WB cabinet, as last seen.
        kind: One of :class:`..services.campaigns.CampaignKind` — what sort of
            campaign it is, which is what the picker sorts by.
        first_seen_at: When this test first read counters from it.
        last_seen_at: When it last did. A campaign switched off mid-test keeps
            its rows and stops moving; the page goes on showing it, because it
            paid for part of what the page is comparing.
    """

    __tablename__ = "ab_test_campaign"
    __table_args__ = {"schema": _SCHEMA}

    test_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.ab_test.id", ondelete="CASCADE"), primary_key=True
    )
    campaign_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    name: Mapped[str] = mapped_column(String(512), server_default="", nullable=False)
    kind: Mapped[str] = mapped_column(String(16), server_default="unknown", nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
