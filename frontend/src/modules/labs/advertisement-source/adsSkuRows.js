/**
 * Advertising per article, subject or brand over a window.
 *
 * The money here is WB's DEDUCTION, not the кабинет's spend history: it is
 * what the margin is computed from, already spread from WB's weekly lump onto
 * the days the ads actually ran and onto articles by their share of the spend
 * (the datapack did that; see the one-pager's notes). So the per-SKU total is
 * expected to differ from the «Потрачено» card above it — two sources, both
 * stated on the page.
 *
 * ДРР of a group is always re-derived from summed money (Σ реклама ÷ Σ выручка),
 * never averaged from its members' ratios — a mean of ratios weights a SKU that
 * sold twice the same as one that sold two hundred times.
 *
 * Ported from the finmodel one-pager (`labs/finmodel/tabs/ads.js`) with the
 * arithmetic unchanged. Pure: datapack in, rows out.
 */

/** The cuts the table offers; `col` heads the first column, `by` ends the title. */
export const AD_GROUPS = [
  { id: 'sku', name: 'Артикулы', col: 'Артикул', by: 'артикулам' },
  { id: 'subject', name: 'Предметы', col: 'Предмет', by: 'предметам' },
  { id: 'brand', name: 'Бренды', col: 'Бренд', by: 'брендам' },
]

/** What a missing subject or brand reads as — and groups under. */
const NONE = '—'

/** Column positions of a packed table, by name. */
function columns(names) {
  return Object.fromEntries(names.map((name, i) => [name, i]))
}

/**
 * Ads, revenue at both bases and orders per `nm_id` over [from, to].
 *
 * P&L days are WB settlement days; order days are order days. They are summed
 * over the same calendar window anyway, exactly as the one-pager does.
 *
 * @returns {Object<number, {ads: number, revenue: number, card: number, orders: number}>}
 */
export function sliceBySku(pack, from, to) {
  const out = {}
  const at = (nmId) => (out[nmId] ??= { ads: 0, revenue: 0, card: 0, orders: 0 })

  const pnl = columns(pack.pnl_daily_cols)
  for (const row of pack.pnl_daily) {
    const day = row[pnl.d]
    if (day < from || day > to) continue
    const sku = at(row[pnl.nm_id])
    sku.ads += row[pnl.ads]
    sku.revenue += row[pnl.revenue]
    sku.card += row[pnl.card]
  }

  const orders = columns(pack.orders_daily_cols)
  for (const row of pack.orders_daily) {
    const day = row[orders.d]
    if (day < from || day > to) continue
    at(row[orders.nm_id]).orders += row[orders.orders]
  }
  return out
}

/** Revenue at the chosen base: WB's realisation price, or the card price before СПП. */
export function revenueAt(figures, revBase) {
  if (!figures) return 0
  return (revBase === 'card' ? figures.card : figures.revenue) || 0
}

/** Articles that are on sale — the datapack also carries code-only placeholders. */
function liveSkus(pack) {
  return pack.skus.filter((sku) => sku.nm_id != null)
}

/**
 * The кабинет's ДРР for the window: every live article's deducted ads over its
 * revenue. Taken over ALL of them, not the table's rows, so the card does not
 * move when a filter does.
 *
 * @returns {{ads: number, revenue: number, drr: number|null}}
 */
export function cabinetDrr(pack, slice, revBase) {
  let ads = 0
  let revenue = 0
  for (const sku of liveSkus(pack)) {
    ads += slice[sku.nm_id]?.ads || 0
    revenue += revenueAt(slice[sku.nm_id], revBase)
  }
  return { ads, revenue, drr: revenue ? ads / revenue : null }
}

/**
 * One row per live article that advertised or sold in the window.
 *
 * `promo` is the article's bonus-paid spend over the whole spend FILE, not the
 * window: WB sends the daily bonus without an article, so only the file total
 * can be attributed.
 *
 * @returns {Array<{label: string, subject: string, brand: string, ads: number,
 *   revenue: number, orders: number, promo: number, drr: number|null}>}
 */
export function skuAdRows(pack, slice, revBase) {
  return liveSkus(pack)
    .map((sku) => {
      const figures = slice[sku.nm_id]
      const ads = figures?.ads || 0
      const revenue = revenueAt(figures, revBase)
      return {
        label: sku.code,
        subject: sku.subject || NONE,
        brand: sku.brand || NONE,
        ads,
        revenue,
        orders: figures?.orders || 0,
        promo: sku.ads_hist?.promo || 0,
        drr: revenue ? ads / revenue : null,
      }
    })
    .filter((row) => row.ads > 0 || row.revenue > 0)
}

/** Distinct subjects and brands, alphabetical, for the filter selects. */
export function filterOptions(rows) {
  const sorted = (values) => [...new Set(values)].sort((a, b) => a.localeCompare(b, 'ru'))
  return {
    subjects: sorted(rows.map((row) => row.subject)),
    brands: sorted(rows.map((row) => row.brand)),
  }
}

/**
 * Rows matching the subject/brand filters and the search text. The text is
 * matched against the article, subject and brand, case-insensitively.
 */
export function pickRows(rows, { query = '', subject = '', brand = '' }) {
  const needle = query.trim().toLowerCase()
  return rows.filter((row) => {
    if (subject && row.subject !== subject) return false
    if (brand && row.brand !== brand) return false
    if (!needle) return true
    return [row.label, row.subject, row.brand].some((text) => text.toLowerCase().includes(needle))
  })
}

/**
 * The same money at a coarser grain. A group row carries `n`, the number of
 * articles in it; an article row does not.
 */
export function groupRows(rows, group) {
  if (group === 'sku') return rows
  const byKey = {}
  for (const row of rows) {
    const key = row[group]
    const sums = (byKey[key] ??= { label: key, ads: 0, revenue: 0, orders: 0, promo: 0, n: 0 })
    sums.ads += row.ads
    sums.revenue += row.revenue
    sums.orders += row.orders
    sums.promo += row.promo
    sums.n += 1
  }
  return Object.values(byKey).map((sums) => ({
    ...sums,
    drr: sums.revenue ? sums.ads / sums.revenue : null,
  }))
}

/** The «Итого» of whatever rows the table holds, ДРР re-derived from the sums. */
export function sumRows(rows) {
  const sums = { ads: 0, revenue: 0, orders: 0, promo: 0 }
  for (const row of rows) {
    sums.ads += row.ads
    sums.revenue += row.revenue
    sums.orders += row.orders
    sums.promo += row.promo
  }
  return { ...sums, drr: sums.revenue ? sums.ads / sums.revenue : null }
}
