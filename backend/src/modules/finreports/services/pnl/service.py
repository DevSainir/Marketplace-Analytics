"""Read-side service for the profit-and-loss statement.

Orchestration only: pull the settlement aggregates and the seller's cost prices,
hand each bucket to :func:`~.statement.build_statement`, and attach the caveats
that tell the reader what the numbers do *not* cover.

Those caveats are load-bearing. A P&L that quietly reports a 90 % margin because
only 15 % of the units it sold have a cost on file is worse than no P&L at all,
so coverage and completeness travel with the figures instead of being something
the reader has to think to check.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from src.modules.finreports.repos import (
    CostPriceRepository,
    FinancialReportRepository,
    PnlGrouping,
    PnlRepository,
    ReasonAmount,
    SettlementAggregate,
)
from src.modules.finreports.schemas.pnl import PnlResponse, PnlStatement, ReasonShare
from src.modules.finreports.services.pnl.statement import build_statement

_ZERO = Decimal(0)

#: Below this share of net units covered by a cost price, the profit lines are
#: reported but flagged: the shortfall is large enough that the margin says more
#: about the missing costs than about the business.
_COVERAGE_WARN_PCT = Decimal(90)

#: Charge columns that get a ``bonus_type_name`` drill-down on the statement.
_BREAKDOWN_COLUMNS = ("delivery_rub", "storage_fee", "penalty", "deduction")


class PnlService:
    """Builds the settlement-basis P&L for a workspace and window."""

    def __init__(
        self,
        *,
        pnl_repo: PnlRepository,
        cost_repo: CostPriceRepository,
        report_repo: FinancialReportRepository,
    ) -> None:
        """Wire the read service from its repositories."""
        self._pnl = pnl_repo
        self._costs = cost_repo
        self._reports = report_repo

    async def get_statement(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        grouping: PnlGrouping,
    ) -> PnlResponse:
        """Return the P&L for the window, plus its per-bucket breakdown.

        Args:
            workspace_id: Owning workspace.
            date_from: Inclusive settlement-date start.
            date_to: Inclusive settlement-date end.
            grouping: How the buckets are cut (weekly report, month, or SKU).

        Returns:
            The whole-window statement, the buckets, and the caveats.
        """
        totals = await self._pnl.aggregate(
            workspace_id=workspace_id,
            date_from=date_from,
            date_to=date_to,
            grouping=PnlGrouping.TOTAL,
        )
        if not totals:
            raise ValueError("empty aggregate")  # pragma: no cover - guarded below
        total_aggregate = totals[0]
        currency = total_aggregate.currency or "KGS"
        costs = await self._costs.costs_by_nm_id(workspace_id=workspace_id, currency=currency)

        reasons = {
            column: await self._pnl.reason_breakdown(
                workspace_id=workspace_id, date_from=date_from, date_to=date_to, column=column
            )
            for column in _BREAKDOWN_COLUMNS
        }

        total_cogs, total_units = self._cogs_for(
            await self._pnl.cogs_inputs(
                workspace_id=workspace_id,
                date_from=date_from,
                date_to=date_to,
                grouping=PnlGrouping.TOTAL,
            ),
            costs,
        )
        total = self._compose(
            total_aggregate,
            key=None,
            label="Итого за период",
            cogs=total_cogs.get(None, _ZERO),
            cogs_units=total_units.get(None, 0),
            reasons=reasons,
        )

        buckets = await self._buckets(
            workspace_id=workspace_id,
            date_from=date_from,
            date_to=date_to,
            grouping=grouping,
            costs=costs,
        )
        notes = await self._notes(
            workspace_id=workspace_id,
            date_from=date_from,
            date_to=date_to,
            total=total,
            aggregate=total_aggregate,
        )
        return PnlResponse(
            date_from=date_from,
            date_to=date_to,
            grouping=str(grouping),
            total=total,
            buckets=buckets,
            notes=notes,
        )

    async def get_settled_span(self, *, workspace_id: uuid.UUID) -> tuple[date, date] | None:
        """Return the first and last day WB has actually settled for a кабинет.

        Read off the report headers — a hundred rows — rather than off the
        settlement detail, which is where the same two dates would cost a pass
        over three quarters of a gigabyte. It is what «Вся история» means and
        what a preset ends on: «30 дней» measured to today would include days no
        WB report covers yet and read as a collapse in sales.

        Returns:
            ``(first, last)``, or ``None`` when nothing has been harvested.
        """
        periods = await self._reports.list_periods(workspace_id=workspace_id)
        if not periods:
            return None
        return (min(row[1] for row in periods), max(row[2] for row in periods))

    async def get_buckets(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        grouping: PnlGrouping,
        currency: str = "",
    ) -> list[PnlStatement]:
        """Return ONLY the buckets of a cut, without the statement around them.

        :meth:`get_statement` answers a different question and pays for it: a
        whole-window total, four ``bonus_type_name`` drill-downs and the caveat
        queries, each a separate pass over the same settlement rows. A consumer
        that draws a chart needs none of that, and on a multi-year window those
        extra passes are the difference between a page and a timeout — measured
        at ~7 s per pass over this service's largest кабинет.

        The buckets themselves are composed by the same code path
        :meth:`get_statement` uses, so the two cannot drift.

        Args:
            workspace_id: Owning workspace.
            date_from: Inclusive settlement-date start.
            date_to: Inclusive settlement-date end.
            grouping: How the buckets are cut.
            currency: The window's settlement currency, when the caller already
                knows it. Cost prices in another currency are dropped, so it has
                to be resolved — but resolving it is itself a pass over the
                window, and a caller that has just read the same window from a
                cut that carries it should not pay for a second one.

        Returns:
            One statement per bucket; empty for ``TOTAL``, which has no buckets.
        """
        if not currency:
            currency = await self._pnl.window_currency(
                workspace_id=workspace_id, date_from=date_from, date_to=date_to
            )
        costs = await self._costs.costs_by_nm_id(workspace_id=workspace_id, currency=currency)
        return await self._buckets(
            workspace_id=workspace_id,
            date_from=date_from,
            date_to=date_to,
            grouping=grouping,
            costs=costs,
        )

    async def _buckets(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        grouping: PnlGrouping,
        costs: dict[int, Decimal],
    ) -> list[PnlStatement]:
        """Build one statement per bucket of the requested grouping."""
        if grouping is PnlGrouping.TOTAL:
            return []
        aggregates = await self._pnl.aggregate(
            workspace_id=workspace_id, date_from=date_from, date_to=date_to, grouping=grouping
        )
        cogs, units = self._cogs_for(
            await self._pnl.cogs_inputs(
                workspace_id=workspace_id, date_from=date_from, date_to=date_to, grouping=grouping
            ),
            costs,
        )
        # WB's stated period is only the truth for this bucket when the request
        # covers the whole report. Ask for three days inside a week and the bucket
        # holds three days of figures — stamping it «2026-07-13 — 2026-07-19»
        # would label a partial figure with a full period.
        periods: dict[object, tuple[date, date]] = (
            {
                r[0]: (r[1], r[2])
                for r in await self._reports.list_periods(workspace_id=workspace_id)
                if date_from <= r[1] and r[2] <= date_to
            }
            if grouping is PnlGrouping.WEEK
            else {}
        )
        return [
            self._compose(
                aggregate,
                key=str(aggregate.key),
                label=self._label(aggregate, grouping, periods),
                cogs=cogs.get(aggregate.key, _ZERO),
                cogs_units=units.get(aggregate.key, 0),
                reasons={column: [] for column in _BREAKDOWN_COLUMNS},
                period=periods.get(aggregate.key) if grouping is PnlGrouping.WEEK else None,
            )
            for aggregate in aggregates
        ]

    def _compose(
        self,
        aggregate: SettlementAggregate,
        *,
        key: str | None,
        label: str,
        cogs: Decimal,
        cogs_units: int,
        reasons: dict[str, list[ReasonAmount]],
        period: tuple[date, date] | None = None,
    ) -> PnlStatement:
        """Turn one aggregate into a statement, applying WB's stated period."""
        statement = build_statement(
            aggregate,
            key=key,
            label=label,
            cogs=cogs,
            cogs_units=cogs_units,
            logistics_reasons=_shares(reasons.get("delivery_rub", [])),
            storage_reasons=_shares(reasons.get("storage_fee", [])),
            penalty_reasons=_shares(reasons.get("penalty", [])),
            deduction_reasons=_shares(reasons.get("deduction", [])),
        )
        if period is not None:
            # WB's own period beats min/max(rr_dt): a report routinely settles
            # nothing on its first or last day, and a six-day «week» on a
            # statement is the kind of error nobody catches by eye.
            statement.date_from, statement.date_to = period
        return statement

    @staticmethod
    def _label(
        aggregate: SettlementAggregate,
        grouping: PnlGrouping,
        periods: dict[object, tuple[date, date]],
    ) -> str:
        """Name a bucket the way its grouping is read."""
        if grouping is PnlGrouping.WEEK:
            period = periods.get(aggregate.key)
            if period:
                return f"{period[0].isoformat()} — {period[1].isoformat()}"
            return f"Отчёт №{aggregate.key}"
        if grouping is PnlGrouping.MONTH:
            return str(aggregate.key)[:7] if aggregate.key else "—"
        if grouping is PnlGrouping.DAY:
            return str(aggregate.key) if aggregate.key else "—"
        return aggregate.label or f"nm {aggregate.key}"

    @staticmethod
    def _cogs_for(
        rows: list[tuple[object, int, int]], costs: dict[int, Decimal]
    ) -> tuple[dict[object, Decimal], dict[object, int]]:
        """Total the cost of goods per bucket, counting only costed SKUs.

        A SKU with no cost on file contributes neither money nor units, so the
        coverage percentage the statement reports is the true share of what was
        sold that the margin actually accounts for.
        """
        cogs: dict[object, Decimal] = {}
        units: dict[object, int] = {}
        for bucket, nm_id, net_units in rows:
            cost = costs.get(nm_id)
            if cost is None:
                continue
            cogs[bucket] = cogs.get(bucket, _ZERO) + cost * net_units
            units[bucket] = units.get(bucket, 0) + net_units
        return cogs, units

    async def _notes(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        total: PnlStatement,
        aggregate: SettlementAggregate,
    ) -> list[str]:
        """Assemble the caveats that qualify the statement."""
        notes: list[str] = []
        coverage = total.cogs_coverage_pct
        if total.net_units and (coverage is None or coverage < _COVERAGE_WARN_PCT):
            notes.append(
                f"Себестоимость задана для {total.cogs_units} из {total.net_units} проданных "
                f"единиц ({coverage or 0}%). Прибыль занижена по непокрытым SKU — "
                "задайте себестоимость в разделе «Себестоимость»."
            )
        sale_rows, with_revenue = await self._pnl.revenue_coverage(
            workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        if sale_rows and with_revenue < sale_rows:
            # Logistics, storage and penalties are complete for such a window
            # (those columns always existed), so «итого к оплате» would show a
            # full period of withholdings against a partial payout — a large,
            # entirely plausible loss.
            notes.append(
                f"Выручка заполнена только для {with_revenue} из {sale_rows} строк продаж "
                "за период: остальные ещё не выгружены из WB. «Итого к оплате» и прибыль "
                "занижены — запустите scripts/backfill_pnl_columns.py."
            )
        unknown = await self._pnl.unclassified_opers(
            workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        if unknown:
            notes.append(
                "WB прислал незнакомые типы операций — они попали в расходы, но не "
                f"в штуки и выплаты: {', '.join(sorted(unknown))}."
            )
        if total.wb_commission < _ZERO:
            # Real, and surprising enough to need saying: WB funds the СПП out of
            # its own reward, so when the discount it grants exceeds its
            # commission rate the net «комиссия» turns into a subsidy. Measured
            # on this seller's 2025: -859 899 KGS, i.e. WB paid out more than
            # buyers paid in. Without this line a reader assumes a sign bug.
            notes.append(
                "Комиссия WB за период отрицательная: скидка WB (СПП) превысила её "
                "собственное вознаграждение, и WB доплатила продавцу сверх того, "
                "что заплатили покупатели. Это не ошибка расчёта."
            )
        if total.acquiring_billed_apart != _ZERO:
            notes.append(
                f"«Комиссия за организацию платежа» ({total.acquiring_billed_apart} "
                f"{total.currency}) выставляется WB отдельно и НЕ удержана из выплаты — "
                "в расходы отчёта она не включена."
            )
        if aggregate.rebill_logistic_cost != _ZERO:
            notes.append(
                "Строка «Возмещение издержек по перевозке» учтена как удержание. "
                "WB прекратил эту операцию 10.05.2025."
            )
        notes.append(
            "Отчёт построен только по еженедельной детализации WB. Налоги, зарплаты, "
            "аренда и реклама, оплаченная с баланса WB, в него не входят."
        )
        return notes


def _shares(reasons: list[ReasonAmount]) -> list[ReasonShare]:
    """Map repository reason rows onto the response DTO."""
    return [ReasonShare(reason=r.reason, amount=r.amount, rows=r.rows) for r in reasons]
