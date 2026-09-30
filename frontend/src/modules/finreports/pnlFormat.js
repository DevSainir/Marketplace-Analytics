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
import { inject, provide, unref } from 'vue'

import { formatMoney, formatNumber, formatPercent } from '@/core/utils/format'

/** A number, or `null` for «not known» — never 0 for a gap. */
export const num = (value) =>
  value === null || value === undefined || value === '' ? null : Number(value)

/** Money with the sign of its currency («57 600с»); «—» when unknown. */
export const money = (value, currency = '') =>
  num(value) === null ? '—' : formatMoney(num(value), currency)

const PNL_CURRENCIES = Symbol('pnl-currencies')

/**
 * Declare what the P&L's money is in, once, for every table, card and total
 * under the page: `{settlement, ads}` — the payout's currency, and the
 * campaigns' (RUB before WB moved the ad account on 2026-08-20). A provider
 * rather than a prop threaded through six components, one of them already at
 * the 250-line ceiling.
 *
 * @param {import('vue').Ref<{settlement?: string, ads?: string[]}>} currencies
 */
export function providePnlCurrencies(currencies) {
  provide(PNL_CURRENCIES, currencies)
}

/**
 * The two money formatters a P&L component needs: `money` for everything the
 * settlement report says, `adMoney` for «Реклама» and «Бонусы». Without a
 * provider (a component mounted alone) both print bare numbers.
 *
 * @returns {{money: (value: unknown) => string, adMoney: (value: unknown) => string}}
 */
export function usePnlMoney() {
  const currencies = inject(PNL_CURRENCIES, null)
  const current = () => unref(currencies) ?? {}
  return {
    money: (value) => money(value, current().settlement ?? ''),
    adMoney: (value) => money(value, current().ads ?? []),
  }
}

/** A percentage; «—» when unknown. */
export const pct = (value) => (num(value) === null ? '—' : formatPercent(num(value)))

/** A unit count; «—» when unknown. */
export const units = (value) => (num(value) === null ? '—' : formatNumber(num(value)))
