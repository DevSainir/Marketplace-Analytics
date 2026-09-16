/**
 * «Выручка по категории»: folding the per-article rows into bars.
 *
 * Pure functions, and deliberately on this side of the wire. Grouping, sorting
 * and the price base used to be query parameters, so every click cost a round
 * trip over the whole settlement window — seconds, for arithmetic over a few
 * dozen rows the browser already holds.
 *
 * One rule carries through: a bar reports no margin at all as soon as one of
 * its articles has none. Letting the costed half stand would rank a group above
 * fully-costed ones for being less well documented.
 */

/** Label for an article WB never gave a subject or a brand. */
const UNNAMED = '(не указан)'

/** How the block may be cut. */
export const CUTS = [
  { key: 'sku', label: 'Артикулы' },
  { key: 'subject', label: 'Предметы' },
  { key: 'brand', label: 'Бренды' },
]

/** What the bars may be ranked by. */
export const SORTS = [
  { key: 'revenue', label: 'По выручке' },
  { key: 'margin', label: 'По марже' },
]

/** Which price base the figures are shown at. */
export const BASES = [
  { key: 'paid', label: 'Цена реализации' },
  { key: 'seller', label: 'Цена селлера — до СПП' },
]

/** Revenue of one row at the requested base. */
export function revenueOf(row, base) {
  return Number(base === 'seller' ? row.revenue_seller : row.revenue_paid)
}

/** The `(key, label)` a row falls under for the requested cut. */
function bucketOf(row, cut) {
  if (cut === 'subject') return [row.subject || UNNAMED, row.subject || UNNAMED]
  if (cut === 'brand') return [row.brand || UNNAMED, row.brand || UNNAMED]
  return [String(row.nm_id), row.code]
}

/**
 * Fold the rows into ranked bars.
 *
 * @param {Array<object>} rows Per-article rows from the API.
 * @param {{cut: string, base: string, sort: string}} options
 * @returns {Array<object>} Bars, largest first by the chosen metric, each with
 *   its share of the visible total and its own margin percentage.
 */
export function buildCategories(rows, { cut, base, sort }) {
  const grouped = new Map()
  for (const row of rows) {
    const [key, label] = bucketOf(row, cut)
    const bucket = grouped.get(key) ?? {
      key,
      label,
      revenue: 0,
      margin: 0,
      costed: true,
      soldUnits: 0,
      skuCount: 0,
    }
    bucket.revenue += revenueOf(row, base)
    bucket.soldUnits += Number(row.sold_units)
    bucket.skuCount += 1
    if (row.margin === null || row.margin === undefined) bucket.costed = false
    else bucket.margin += Number(row.margin)
    grouped.set(key, bucket)
  }

  const bars = [...grouped.values()].map((bucket) => ({
    ...bucket,
    margin: bucket.costed ? bucket.margin : null,
  }))

  // Shares are of the block's own totals, so the column adds up to 100 % for a
  // reader who checks. Account-level money is not in these rows at all — it has
  // no article, subject or brand — and so is not in the denominator either.
  const revenueTotal = bars.reduce((sum, bar) => sum + bar.revenue, 0)
  const marginTotal = bars.reduce((sum, bar) => sum + (bar.margin ?? 0), 0)

  for (const bar of bars) {
    bar.revenueShare = revenueTotal ? (bar.revenue / revenueTotal) * 100 : 0
    bar.marginShare = bar.margin === null || !marginTotal ? null : (bar.margin / marginTotal) * 100
    bar.marginPct = bar.margin === null || !bar.revenue ? null : (bar.margin / bar.revenue) * 100
  }

  // Sorting by margin puts the loss-makers at the bottom rather than dropping
  // them: a negative bar is the one a seller most needs to see.
  const metric = sort === 'margin' ? (bar) => bar.margin ?? -Infinity : (bar) => bar.revenue
  bars.sort((a, b) => metric(b) - metric(a))
  return bars
}
