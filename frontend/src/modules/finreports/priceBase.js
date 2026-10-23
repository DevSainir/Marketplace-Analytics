/**
 * At which price the P&L shows its revenue: the seller's own, or what the buyer paid.
 *
 * WB settles every sale twice over. The seller price is the seller's price
 * after the agreed discount and before the WB discount — what WB's commission
 * and the payout are pegged to. The customer price is what the buyer actually
 * paid after the WB discount, and it is the sale on WB's own report page.
 * Neither is wrong; showing one while the seller compares against the other is
 * what made "Sales" look like a mistake.
 *
 * So the page carries a switch, like the summary, and every figure that
 * divides by revenue follows it: the revenue itself, the average price, the
 * logistics share, ACoS and the margin, in the dashboard, the table, its
 * "Total", the phone cards and the size drill-down. What does not divide by
 * revenue does not move — the payout, the profit in money, ROI (profit over
 * cost) and the WB discount itself, which is the gap between the two bases.
 *
 * The seller's price is the default, for the reason the shares moved to it on
 * 26 Sep 2026: the WB discount is WB's own and WB changes it weekly, so at the
 * buyer's price the logistics share rises whenever WB raises it, with the
 * seller's costs unchanged (docs/finreports/PNL.md).
 */
import { inject, provide, unref } from 'vue'

/** The switch, the seller's price first. Same wording as the summary's. */
export const PRICE_BASES = [
  { key: 'seller', label: 'Seller price — before WB discount', caption: 'At seller price' },
  { key: 'paid', label: 'Customer price', caption: 'At customer price' },
]

/** Pick the figure for the chosen base. */
export function atBase(base, seller, paid) {
  return base === 'paid' ? paid : seller
}

/** `part` as a percentage of `whole`, or `null` when either is unknown or the whole is 0. */
export function shareOf(part, whole) {
  if (part === null || part === undefined || whole === null || whole === undefined) return null
  return Number(whole) ? (Number(part) / Number(whole)) * 100 : null
}

/**
 * ACoS — advertising as a percentage of sales, `null` unless sales are positive.
 *
 * Sales are net of returns, so an article can return more than it sold over a
 * window; advertising over that is a negative ACoS, which means nothing.
 */
export function drrShare(part, whole) {
  return Number(whole) > 0 ? shareOf(part, whole) : null
}

/**
 * The revenue-dependent figures of one size row (or the sizes' totals).
 *
 * The backend sends them at the seller's price; at the buyer's they are
 * recomputed from the same row so price x units still equals the revenue.
 *
 * @param {object} size A `PnlSizeRow`, or the response's `totals`.
 * @param {string} base `'seller'` or `'paid'`.
 * @returns {{price: number|null, revenue: number, logisticsPct: number|null}}
 */
export function sizeAtBase(size, base) {
  const revenue = Number(atBase(base, size.revenue_seller_price, size.revenue_paid))
  const net = Number(size.sold_units) - Number(size.returned_units)
  return {
    price: net ? revenue / net : null,
    revenue,
    logisticsPct: shareOf(size.logistics_total, revenue),
  }
}

const PRICE_BASE = Symbol('pnl-price-base')

/** Hand the page's chosen base to every P&L component below it. */
export function providePriceBase(base) {
  provide(PRICE_BASE, base)
}

/**
 * The chosen base, as a getter so it stays reactive through `inject`.
 * The seller's price when nothing provided one — a component rendered on its own.
 */
export function usePriceBase() {
  const base = inject(PRICE_BASE, null)
  return () => unref(base) ?? 'seller'
}
