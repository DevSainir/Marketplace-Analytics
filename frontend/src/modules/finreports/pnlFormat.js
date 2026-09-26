/**
 * The P&L's cell formatters — one copy for the table, the phone cards, the
 * totals and the size drill-down.
 *
 * There were five, all spelling «a missing figure is "—", not 0» slightly
 * differently, and one of them also had to convert strings: the backend
 * serialises `Decimal` as a string (so money keeps its kopecks), and
 * `formatPercent` answers «—» for anything that is not a number, which emptied
 * a whole column of the size table once. Every formatter here converts, so no
 * caller has to remember which endpoint sends strings.
 */
import { formatMoney, formatNumber, formatPercent } from '@/core/utils/format'

/** A number, or `null` for «not known» — never 0 for a gap. */
export const num = (value) =>
  value === null || value === undefined || value === '' ? null : Number(value)

/** Money without a currency sign; «—» when unknown. */
export const money = (value) => (num(value) === null ? '—' : formatMoney(num(value), ''))

/** A percentage; «—» when unknown. */
export const pct = (value) => (num(value) === null ? '—' : formatPercent(num(value)))

/** A unit count; «—» when unknown. */
export const units = (value) => (num(value) === null ? '—' : formatNumber(num(value)))
