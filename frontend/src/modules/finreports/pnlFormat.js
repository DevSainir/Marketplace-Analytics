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
 * under the page: `{settlement}` — the payout's currency. A provider rather
 * than a prop threaded through six components, one of them already at the
 * 250-line ceiling.
 *
 * @param {import('vue').Ref<{settlement?: string}>} currencies
 */
export function providePnlCurrencies(currencies) {
  provide(PNL_CURRENCIES, currencies)
}

/**
 * The money formatter a P&L component needs. Without a provider (a component
 * mounted alone) it prints bare numbers.
 *
 * «Реклама» and «Бонусы» are signed in the payout's currency too: WB billed
 * old campaigns in roubles until 22.09.2026, and since 02.10.2026 those roubles
 * are converted to the кабинет's currency where they are stored, at the Bank
 * of Russia rate of their day. The report's caveat names any rouble row the
 * conversion could not reach.
 *
 * @returns {{money: (value: unknown) => string}}
 */
export function usePnlMoney() {
  const currencies = inject(PNL_CURRENCIES, null)
  return {
    money: (value) => money(value, unref(currencies)?.settlement ?? ''),
  }
}

/** A percentage; «—» when unknown. */
export const pct = (value) => (num(value) === null ? '—' : formatPercent(num(value)))

/** A unit count; «—» when unknown. */
export const units = (value) => (num(value) === null ? '—' : formatNumber(num(value)))
