"""Bank of Russia exchange rates, and the mark a converted money row carries.

WB moved every ad account from RUB to KGS on 2026-08-20; a KGS кабинет's
earlier advertising — and the tail of campaigns created before the move — is
stored by WB in roubles. Those rows are converted to the кабинет's own
currency at the rate WB itself uses for every RUB→KGS conversion it makes: the
Bank of Russia's, of the day (verified to five decimals on five dates of
2026-07..09, see wildberries-api/references/currencies.md).

The rates are loaded once (migration ``c4e8a2f71d39``) rather than harvested:
the RUB campaigns stopped spending on 2026-09-22, so there is no new rouble
spend to convert. A RUB row dated past the last loaded rate stays in roubles,
and every screen then shows «—» for the sums it would have mixed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

_SCHEMA: str = "monitoring"


class CbrRate(Base):
    """One Bank of Russia rate: ``value`` roubles for ``nominal`` units of ``currency``.

    Dated as the Bank dates it — the day the rate takes effect. It publishes on
    working days only, so a Sunday's rate is Saturday's row (2026-07-12 was
    converted by WB at the rate dated 11.07): a day reads the latest row on or
    before it.
    """

    __tablename__ = "cbr_rate"
    __table_args__ = ({"schema": _SCHEMA},)

    currency: Mapped[str] = mapped_column(String(8), primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    nominal: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)


class FxConverted:
    """The mark of a money row converted from another currency.

    ``fx_from`` is what WB stated the money in, ``fx_rate`` the factor it was
    multiplied by (units of the stored currency per rouble). A row as WB served
    it has ``fx_rate`` NULL — a re-harvest writes it that way again, and the
    conversion sweep picks it up (``repos/ad_money.py``).
    """

    fx_from: Mapped[str] = mapped_column(String(8), server_default="", nullable=False)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
