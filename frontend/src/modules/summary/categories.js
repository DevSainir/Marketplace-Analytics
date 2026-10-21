/**
 * «Выручка по категории»: folding the per-article rows into bars.
 *
 * Pure functions, and deliberately on this side of the wire. Grouping, sorting
 * and the price base used to be query parameters, so every click cost a round
 * trip over the whole settlement window — seconds, for arithmetic over a few
 * dozen rows the browser already holds.
 *
 * Cut by «Группы» it follows the heatmap: an article sits in every group it
 * is in, the rest under «Без группы» (`splitBy`).
 *
 * One rule carries through: a bar reports no margin at all as soon as one of
 * its articles has none. Letting the costed half stand would rank a group above
 * fully-costed ones for being less well documented.
 */
import { splitBy } from '@/modules/heatmap'

/** What the bars may be ranked by. */
export const SORTS = [
  { key: 'revenue', label: 'По выручке' },
  { key: 'margin', label: 'По марже' },
]

/**
 * Which price base the figures are shown at, the seller's own first.
 *
 * It is also the default. WB's SPP is a discount WB funds, so «цена реализации»
 * is what the buyer paid and «цена селлера» is what the payout is actually
 * pegged to — the base a seller plans against.
 */
export const BASES = [
  { key: 'seller', label: 'Цена селлера — до СПП' },
  { key: 'paid', label: 'Цена реализации' },
]

/** Revenue of one row at the requested base. */
export function revenueOf(row, base) {
  return Number(base === 'seller' ? row.revenue_seller : row.revenue_paid)
}

/** The article rows a bar is made of — one bar per article, or per subject, brand or group. */
function bucketsOf(rows, cut, groups) {
  if (cut === 'sku')
    return rows.map((row) => ({ key: String(row.nm_id), label: row.code, items: [row] }))
  return splitBy(rows, cut, {
    nmId: (row) => row.nm_id,
    subject: (row) => row.subject,
    brand: (row) => row.brand,
    groups,
  })
}

/**
 * Fold the rows into ranked bars.
 *
 * @param {Array<object>} rows Per-article rows from the API.
 * @param {{cut: string, base: string, sort: string, groups?: Array<object>}} options
 *   `groups` — the workspace's «Группы», for the `group` cut.
 * @returns {Array<object>} Bars, largest first by the chosen metric, each with
 *   its share of the visible total and its own margin percentage.
 */
export function buildCategories(rows, { cut, base, sort, groups = [] }) {
  const grouped = bucketsOf(rows, cut, groups).map(({ key, label, items }) => {
    const bucket = { key, label, revenue: 0, margin: 0, costed: true, soldUnits: 0, skuCount: 0 }
    for (const row of items) {
      bucket.revenue += revenueOf(row, base)
      bucket.soldUnits += Number(row.sold_units)
      bucket.skuCount += 1
      if (row.margin === null || row.margin === undefined) bucket.costed = false
      else bucket.margin += Number(row.margin)
    }
    return bucket
  })

  const bars = grouped.map((bucket) => ({
    ...bucket,
    margin: bucket.costed ? bucket.margin : null,
  }))

  // Shares are of the block's own totals, so the column adds up to 100 % for a
  // reader who checks. Account-level money is not in these rows at all — it has
  // no article, subject or brand — and so is not in the denominator either.
  // By group an article can sit in two bars, so there the totals are the
  // articles' own, and the shares are each group's part of the whole — they
  // can add up to more than 100 %, as overlapping groups do.
  const byArticle = cut === 'group'
  const revenueTotal = byArticle
    ? rows.reduce((sum, row) => sum + revenueOf(row, base), 0)
    : bars.reduce((sum, bar) => sum + bar.revenue, 0)
  const marginTotal = byArticle
    ? rows.reduce(
        (sum, row) =>
          sum + (row.margin === null || row.margin === undefined ? 0 : Number(row.margin)),
        0,
      )
    : bars.reduce((sum, bar) => sum + (bar.margin ?? 0), 0)

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
