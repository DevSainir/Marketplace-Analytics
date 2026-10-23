/**
 * The three charts' lines, built from the day payload.
 *
 * Pure functions, out of the view: they carry the rules that decide when a
 * point is missing rather than zero, and those are worth a test each. The view
 * keeps only the titles and the colours.
 */

/** The seller's own price, or the one the buyer paid. */
export function dayRevenue(day, base) {
  const value = base === 'seller' ? day.revenue_seller : day.revenue_paid
  return value === null || value === undefined ? null : Number(value)
}

/**
 * DRR — advertising as a share of what it sold, per day, in percent.
 *
 * `null` on either side of the division, never zero: a day with no advertising
 * statistics and a day with no price to value its orders at are both "we don't
 * know", and zero there would read as free advertising or as infinite DRR.
 */
export function drr(spend, base) {
  if (spend === null || spend === undefined) return null
  // Not positive: the day returned more than it sold, and advertising over a
  // negative sum is a negative DRR, which means nothing — withheld like a day
  // without sales.
  if (base === null || base === undefined || Number(base) <= 0) return null
  return (Number(spend) / Number(base)) * 100
}

const number = (value) => (value === null || value === undefined ? null : Number(value))

/**
 * "Revenue" — revenue, and margin beside it when the window is fully costed.
 *
 * The margin line is omitted entirely rather than drawn flat: a zero line would
 * be a claim, and a window with an uncosted article does not have the figure to
 * make it.
 */
export function revenueSeries(days, { base, costed }) {
  const lines = [
    { name: 'Revenue', color: 'var(--ui-action)', values: days.map((d) => dayRevenue(d, base)) },
  ]
  if (costed) {
    lines.push({
      name: 'Net profit',
      color: 'var(--ui-pos)',
      values: days.map((day) => number(day.margin)),
    })
  }
  return lines
}

/**
 * "Orders and ACoS by day" — the day's orders against DRR of what they were worth.
 *
 * The ordered money follows the same price base as everything else on the page:
 * a day's orders are worth one thing at the seller's own price and another
 * after WB's SPP, and the advertising is the same money either way.
 */
export function orderSeries(days, { base }) {
  return [
    { name: 'Orders, units', color: 'var(--ui-action)', values: days.map((d) => number(d.orders)) },
    {
      name: 'ACoS (orders)',
      color: 'var(--ui-warn)',
      axis: 'right',
      percent: true,
      values: days.map((day) =>
        drr(day.ad_spend, base === 'seller' ? day.orders_amount_seller : day.orders_amount_paid),
      ),
    },
  ]
}

/** "Sales and ACoS by day" — what WB calculated as sold, against DRR of revenue. */
export function saleSeries(days, { base }) {
  return [
    {
      name: 'Sales, units',
      color: 'var(--ui-action)',
      values: days.map((d) => number(d.sold_units)),
    },
    {
      name: 'ACoS (sales)',
      color: 'var(--ui-warn)',
      axis: 'right',
      percent: true,
      values: days.map((day) => drr(day.ad_spend, dayRevenue(day, base))),
    },
  ]
}
