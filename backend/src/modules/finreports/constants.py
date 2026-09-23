"""Shared constants for the ``finreports`` module.

Neutral values imported by both the data-access and service layers (so neither
depends on the other). The Cyrillic strings are the exact WB-served labels the
``reportDetailByPeriod``.
"""

from __future__ import annotations

from decimal import Decimal

# --------------------------------------------------------------------------- #
# Harvest concurrency
# --------------------------------------------------------------------------- #
#: Redis key guarding the fleet-wide finance harvest against overlapping runs.
#: Shared by the task that takes the lock and the route that reports it, which
#: is why it is here rather than private to either.
HARVEST_LOCK_KEY: str = "finreports:harvest_finance"

#: How long the lock outlives a harvest that stops renewing it — NOT how long a
#: harvest may run. A live run heartbeats and holds the lock for as long as it
#: takes; this only bounds how long a DEAD one strands the job.
#:
#: Ten minutes, because both of its failure modes are real and pull opposite
#: ways. Too short and a healthy run that blocks its event loop (ingesting 30k
#: settlement rows does) loses the lock to the next tick and gets joined
#: mid-walk. Too long and a killed worker keeps the job stranded: on 2026-08-11
#: an hour-long TTL cost two skipped ticks in one morning — once after the OOM
#: killer took the walk, once after a deploy recreated the worker under it.
#: Ten minutes clears the longest block by a wide margin and is short enough
#: that the next hourly tick recovers on its own.
HARVEST_LOCK_TTL_SECONDS: int = 600

#: How far BEHIND the settlement watermark a reconciliation walk re-reads.
#:
#: The harvest's reachable window only ever moves forward, and it jumps forward
#: to the newest report's stated end. WB does not publish in that order: it
#: forms supplementary reports for single days and starts serving their detail
#: rows later — sometimes days later. Anything landing behind the jump is
#: invisible to a forward-only walk, permanently.
#:
#: Measured, not guessed. Report 983241109 covered 2026-08-31 alone and carried
#: `create_dt` 2026-09-01, yet on 2026-09-06 every one of 80 probes over
#: 31.08..05.09 answered 204 — WB was not serving its rows. On 09-07 the
#: 01.09-06.09 report landed, `max(date_to)` jumped to 09-06, and the day fell
#: out of reach before WB ever served it. Fourteen days puts a comfortable
#: margin on the ~8 observed between the day covered and the day it became
#: fetchable.
RECONCILE_LOOKBACK_DAYS: int = 14

#: How long after a settlement day WB may still be silent before the nightly
#: survey calls it a gap.
#:
#: The survey scans to ``today - this``, not to the newest report we hold, so a
#: week WB has published and we have failed to harvest is inside the range
#: instead of past its end — the blind spot that let 07.09-13.09 go missing from
#: three workspaces on 2026-09-14 with a gap count of zero.
#:
#: Seven days, and the number is a noise floor rather than a deadline. WB forms
#: the weekly report the day after the period ends (period 07.09-13.09 →
#: `create_dt` 14.09; 01.09-06.09 → 07.09; 31.08 → 01.09), so three would
#: usually do. But forming is not serving: report 983241109 was formed on 09-01
#: and still answered 204 on 09-06, and alerting on that would have been an
#: alarm about WB's schedule rather than about our harvest. A day still
#: uncovered a week later is ours.
SETTLEMENT_PUBLICATION_GRACE_DAYS: int = 7

#: How long a formed period may go unserved before we stop asking for it.
#:
#: A period stays on the missing list until its report is HELD — that is what
#: makes a report WB serves days late reachable at all, and it is why 31.08.2026
#: would not be lost again. Unbounded, it is also a slow catastrophe: a period
#: WB will never serve (and those exist — see GAP_REPAIR_COOLDOWN_SECONDS) keeps
#: the probe window's start pinned to it for ever, and the walk span is measured
#: from there. Six months stuck is a 180-day span, 26 weekly windows, six and a
#: half hours of quarter-hourly requests — three times a day, holding the
#: fleet-wide lock and starving every other seller.
#:
#: Fourteen days, matching :data:`RECONCILE_LOOKBACK_DAYS` so the two horizons
#: cannot disagree. The longest WB has ever been late is **eight** days (report
#: 983241109, stamped 01.09.2026 and first served 09.09), so this covers the
#: worst measured case with most of a week to spare.
#:
#: Abandoning is not forgetting. The period stops costing forward probes; it
#: stays a hole in `survey_settlement_gaps` and in the `SettlementHistoryHasGaps`
#: alert, and the reconciliation lookback — the same fourteen days, which is why
#: the two are one number — still re-walks it whenever a thorough pass runs.
SETTLEMENT_PERIOD_ABANDON_DAYS: int = 14

#: How far back the freshness gate asks WB to list reports.
#:
#: The list is one cheap request whatever its width, so this is not a cost
#: question — it is how far back a report WB serves late is still noticed. It
#: must comfortably exceed the longest observed lateness (eight days, report
#: 983241109) and reach past the reconciliation lookback, so a hole the nightly
#: pass can repair is a hole the hourly tick can also see.
SETTLEMENT_LIST_WINDOW_DAYS: int = 45

#: How long an hourly tick waits before re-walking the same workspace's hole.
#:
#: The hourly pass repairs a gap the survey can see instead of leaving it to the
#: nightly rotation, because the rotation takes one workspace a night and a
#: seller short a week does not want to be told it will be looked at on
#: Thursday. Unrationed, though, a hole WB will never serve — and those exist —
#: would have every tick spend a fortnight-wide walk on it forever, holding the
#: fleet-wide harvest lock and starving every other workspace's forward probe of
#: the quarter-hourly budget.
#:
#: Six hours is four attempts a day against the rotation's one every five
#: nights, and it caps a permanently stuck day at four walks a day rather than
#: twenty-four. «Обновить» is deliberately NOT subject to it: a person asking is
#: not a schedule, and the request is one tenant's own.
GAP_REPAIR_COOLDOWN_SECONDS: int = 6 * 60 * 60

#: Redis key prefix for that cooldown, one key per workspace.
GAP_REPAIR_COOLDOWN_PREFIX: str = "finreports:gap-repair:"

#: How long a recorded freshness verdict survives — 30 days, deliberately long.
#:
#: The entry expiring is indistinguishable from "we never checked", and a STALE
#: probe is precisely the evidence that the harvester stopped. A few-hour TTL
#: would erase the one signal the P&L's freshness line exists to show: it would
#: turn "nobody has asked since Tuesday" into a blank, which reads as a page
#: that simply has no such feature.
FRESHNESS_RECORD_TTL_SECONDS: int = 30 * 24 * 60 * 60

#: WB ``supplier_oper_name`` for a logistics (delivery) charge.
LOGISTICS_OPER: str = "Логистика"

#: WB ``supplier_oper_name`` for a penalty row.
PENALTY_OPER: str = "Штраф"



#: FX-invariant), and WB currently sets these uniformly across warehouses
#: (verified live 2026-07-22: base 46, litre 14).
DEFAULT_BOX_DELIVERY_BASE: Decimal = Decimal("46")
DEFAULT_BOX_DELIVERY_LITER: Decimal = Decimal("14")


# --------------------------------------------------------------------------- #
# P&L operation taxonomy
# --------------------------------------------------------------------------- #
# Which ``supplier_oper_name`` values feed which line of the statement. Derived
# by aggregating every money column against every operation over the seller's
# whole settled history (436 742 rows / 133 reports / 2024-01-29..2026-07-26):
# each money column is populated by exactly one family of operations and is zero
# on all the others, which is what makes these groupings a partition rather than
# a guess.
#
# An operation missing from every tuple below contributes nothing to the
# statement, so the P&L service asserts the reverse: any operation it meets that
# is in none of these lists is reported as unclassified rather than dropped.

#: Units and revenue. ``quantity`` is 1 on every one of these rows.
SALE_OPERS: tuple[str, ...] = ("Продажа",)

#: Refunds. WB serves these POSITIVE — money and units alike — so every one of
#: them is subtracted, never summed with the sales.
RETURN_OPERS: tuple[str, ...] = ("Возврат",)

#: ``delivery_rub``. «Коррекция логистики» is the only one that goes negative.
LOGISTICS_OPERS: tuple[str, ...] = ("Логистика", "Коррекция логистики")

#: ``storage_fee``.
STORAGE_OPERS: tuple[str, ...] = ("Хранение", "Коррекция хранения", "Пересчет хранения")

#: ``acceptance``.
ACCEPTANCE_OPERS: tuple[str, ...] = (
    "Платная приемка",
    "Пересчет платной приемки",
    "Обработка товара",
)

#: ``penalty``.
PENALTY_OPERS: tuple[str, ...] = ("Штраф",)

#: ``deduction`` — WB's service invoices, overwhelmingly advertising.
DEDUCTION_OPERS: tuple[str, ...] = ("Удержание",)

#: ``rebill_logistic_cost``. Retired by WB after 2025-05-10; every row carries
#: ``nm_id = 0`` and a constant ``quantity = 2``, so it is company-level money
#: that can never be attributed to a SKU.
REBILL_OPERS: tuple[str, ...] = (
    "Возмещение издержек по перевозке/по складским операциям с товаром",
)

#: Standalone compensations WB pays or withholds outside the sale/return flow.
#: They carry ``quantity = 1`` but share their ``srid`` with no sale, so they are
#: money-only: counting them as units would inflate COGS against stock that was
#: never shipped.
COMPENSATION_OPERS: tuple[str, ...] = (
    "Добровольная компенсация при возврате",
    "Компенсация ущерба",
    "Частичная компенсация брака",
    "Компенсация брака",
    "Компенсация подмененного товара",
    "Компенсация потерянного товара",
    "Компенсация скидки по программе лояльности",
    "Авансовая оплата за товар без движения",
    "Возмещение за выдачу и возврат товаров на ПВЗ",
    "Корректировка эквайринга",
    "Коррекция продаж",
    "Коррекция возвратов",
)

#: Every operation the statement knows how to place.
CLASSIFIED_OPERS: frozenset[str] = frozenset(
    SALE_OPERS
    + RETURN_OPERS
    + LOGISTICS_OPERS
    + STORAGE_OPERS
    + ACCEPTANCE_OPERS
    + PENALTY_OPERS
    + DEDUCTION_OPERS
    + REBILL_OPERS
    + COMPENSATION_OPERS
)


# --------------------------------------------------------------------------- #
# Deduction reasons
# --------------------------------------------------------------------------- #
# «Удержание» is one operation carrying several unrelated costs, told apart only
# by the free-text ``bonus_type_name`` — which embeds an invoice number, so the
# match has to be by substring. Advertising alone is 5 979 875 of the 7 862 125
# KGS ever withheld (95 %), and burying it inside «прочие удержания» would hide
# the seller's single largest controllable cost.
#
# Substring matching against WB's prose is fragile by nature. It is safe *here*
# because an unrecognised label falls through to «Прочие удержания» — a renamed
# invoice line shows up in the wrong bucket, never disappears from the total.

#: Marketing spend billed through «ВБ.Продвижение».
ADVERTISING_DEDUCTION_MARKER: str = "Продвижение"

#: The «Джем» seller-subscription fee.
SUBSCRIPTION_DEDUCTION_MARKER: str = "Джем"

#: Inbound transit delivery of supplies to the warehouse.
TRANSIT_DEDUCTION_MARKER: str = "транзитных поставок"


# --------------------------------------------------------------------------- #
# Acquiring: withheld vs billed separately
# --------------------------------------------------------------------------- #
#: ``payment_processing`` value marking an ``acquiring_fee`` that WB does NOT
#: withhold from ``ppvz_for_pay``.
#:
#: Measured, not assumed. Over the whole 620k-row history the payout identity
#: ``ppvz_for_pay = retail_amount - ppvz_vw - ppvz_vw_nds - acquiring_fee -
#: ppvz_reward`` fails on 5 727 rows, and on 3 293 of them the residual equals
#: ``acquiring_fee`` to the kopeck — every single one carrying this label. Its
#: three siblings («Перевыставление эквайринга», «Компенсация платёжных услуг»,
#: blank) break the identity on 102 rows in total.
#:
#: So this fee is billed elsewhere. Subtracting it from the payout as if it were
#: withheld overstates the seller's acquiring cost by 226 004 KGS across the
#: history and understates WB's commission by the same amount.
SEPARATELY_BILLED_ACQUIRING: str = "Комиссия за организацию платежа с НДС"


# --------------------------------------------------------------------------- #
# The provisional daily tail
# --------------------------------------------------------------------------- #
#: How far behind the settled frontier the daily lane will reach.
#:
#: The tail exists to cover the days between the last settled week and
#: yesterday, which is at most eight or nine days in the ordinary case. A
#: workspace stuck months behind — WB never served a week, the gap repair has not
#: caught up — must not turn that into a hundred daily reports at one request a
#: minute, starving every other seller behind the shared lock. Matching
#: :data:`RECONCILE_LOOKBACK_DAYS` so the two horizons cannot drift: a day the
#: reconciliation pass can still repair weekly is a day this lane can still
#: cover daily.
DAILY_TAIL_LOOKBACK_DAYS: int = 14

#: How long a daily report must be held before its re-read means anything.
#:
#: The open question is whether WB revises a daily report after first serving it.
#: Re-reading one 42 minutes later found it identical, which rules out
#: minute-by-minute top-ups and nothing else, so the measurement that matters is
#: across a day boundary. Anything shorter answers a question nobody asked.
DAILY_TAIL_VERIFY_AFTER_HOURS: int = 24

#: Daily reports re-read per workspace per verification run.
#:
#: Each costs one request on a bucket that serves one a minute and is shared with
#: the settled history's own walk. Three is one report a day plus slack to drain
#: a backlog, and bounds the run at three minutes per workspace.
DAILY_TAIL_VERIFY_LIMIT: int = 3
