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
 * ДРР — advertising as a share of what it sold, per day, in percent.
 *
 * `null` on either side of the division, never zero: a day with no advertising
 * statistics and a day with no price to value its orders at are both «не
 * знаем», and zero there would read as free advertising or as infinite ДРР.
 */
export function drr(spend, base) {
  if (spend === null || spend === undefined) return null
  if (base === null || base === undefined || Number(base) === 0) return null
  return (Number(spend) / Number(base)) * 100
}

const number = (value) => (value === null || value === undefined ? null : Number(value))

/**
 * «Выручка» — revenue, and margin beside it when the window is fully costed.
 *
 * The margin line is omitted entirely rather than drawn flat: a zero line would
 * be a claim, and a window with an uncosted article does not have the figure to
 * make it.
 */
export function revenueSeries(days, { base, costed }) {
  const lines = [
    { name: 'Выручка', color: 'var(--ui-action)', values: days.map((d) => dayRevenue(d, base)) },
  ]
  if (costed) {
    lines.push({
      name: 'Маржа',
      color: 'var(--ui-pos)',
      values: days.map((day) => number(day.margin)),
    })
  }
  return lines
}

/** «Заказы и ДРР в день» — the funnel's count against ДРР of the ordered money. */
export function orderSeries(days) {
  return [
    { name: 'Заказы, шт', color: 'var(--ui-action)', values: days.map((d) => number(d.orders)) },
    {
      name: 'ДРР от заказов',
      color: 'var(--ui-warn)',
      axis: 'right',
      percent: true,
      values: days.map((day) => drr(day.ad_spend, day.orders_amount)),
    },
  ]
}

/** «Продажи и ДРР в день» — what WB calculated as sold, against ДРР of revenue. */
export function saleSeries(days, { base }) {
  return [
    {
      name: 'Продажи, шт',
      color: 'var(--ui-action)',
      values: days.map((d) => number(d.sold_units)),
    },
    {
      name: 'ДРР от продаж',
      color: 'var(--ui-warn)',
      axis: 'right',
      percent: true,
      values: days.map((day) => drr(day.ad_spend, dayRevenue(day, base))),
    },
  ]
}
