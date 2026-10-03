/**
 * The per-article table's rows: grouping, filters, totals and the two ratios.
 *
 * Both ratios are re-derived from summed money, never averaged:
 *
 * * **ДРР от продаж** — spend on SETTLED days over settled sales. The page's
 *   own window may run past the settlement; those days' spend has no sales to
 *   be divided by and stays out of the numerator (the backend sends it apart as
 *   `spend_settled`).
 * * **Доля** — the row's spend over the кабинет's whole spend for the window,
 *   whatever the filter: «доля общих рекламных расходов».
 */

/** The cuts the table offers; `col` heads the first column, `by` ends the title. */
export const AD_GROUPS = [
  { id: 'sku', name: 'Артикулы', col: 'Артикул', by: 'артикулам' },
  { id: 'subject', name: 'Предметы', col: 'Предмет', by: 'предметам' },
  { id: 'brand', name: 'Бренды', col: 'Бренд', by: 'брендам' },
]

/** What a missing subject or brand reads as — and groups under. */
const NONE = '—'

const num = (value) => (value === null || value === undefined ? null : Number(value))

/** ДРР as a 0–1 ratio, `null` when there is nothing to divide by. */
export function drrOf(spendSettled, sales) {
  return sales ? spendSettled / sales : null
}

/** API article rows into table rows. */
export function toRows(skus) {
  return skus.map((sku) => ({
    label: sku.vendor_code,
    nmId: sku.nm_id,
    subject: sku.subject || NONE,
    brand: sku.brand || NONE,
    spend: Number(sku.spend),
    bonus: Number(sku.bonus),
    spendSettled: Number(sku.spend_settled),
    sales: num(sku.sales),
    orders: sku.orders,
  }))
}

/** Distinct subjects and brands, alphabetical, for the filter selects. */
export function filterOptions(rows) {
  const sorted = (values) => [...new Set(values)].sort((a, b) => a.localeCompare(b, 'ru'))
  return {
    subjects: sorted(rows.map((row) => row.subject)),
    brands: sorted(rows.map((row) => row.brand)),
  }
}

/** Rows matching the filters and the search text (article, subject, brand). */
export function pickRows(rows, { query = '', subject = '', brand = '' }) {
  const needle = query.trim().toLowerCase()
  return rows.filter((row) => {
    if (subject && row.subject !== subject) return false
    if (brand && row.brand !== brand) return false
    if (!needle) return true
    return [row.label, row.subject, row.brand, String(row.nmId ?? '')].some((text) =>
      text.toLowerCase().includes(needle),
    )
  })
}

/** Add two nullable counts: unknown stays unknown only when both are. */
const addNullable = (a, b) => (a === null && b === null ? null : (a ?? 0) + (b ?? 0))

/** Sum rows into one, the ratios recomputed by {@link withRatios}. */
function sum(rows, label) {
  return rows.reduce(
    (acc, row) => ({
      ...acc,
      spend: acc.spend + row.spend,
      bonus: acc.bonus + row.bonus,
      spendSettled: acc.spendSettled + row.spendSettled,
      sales: addNullable(acc.sales, row.sales),
      orders: addNullable(acc.orders, row.orders),
    }),
    { label, spend: 0, bonus: 0, spendSettled: 0, sales: null, orders: null, n: rows.length },
  )
}

/** Attach ДРР and the share of the кабинет's spend. */
function withRatios(row, cabinetSpend) {
  return {
    ...row,
    drr: drrOf(row.spendSettled, row.sales),
    share: cabinetSpend ? row.spend / cabinetSpend : null,
  }
}

/**
 * The same money at the chosen grain, with ratios. A group row carries `n`,
 * the number of articles in it.
 */
export function groupRows(rows, group, cabinetSpend) {
  if (group === 'sku') return rows.map((row) => withRatios(row, cabinetSpend))
  const byKey = new Map()
  for (const row of rows) {
    const key = row[group]
    if (!byKey.has(key)) byKey.set(key, [])
    byKey.get(key).push(row)
  }
  return [...byKey].map(([key, members]) => withRatios(sum(members, key), cabinetSpend))
}

/** The «Итого» of whatever the table holds. */
export function totalRow(rows, cabinetSpend) {
  return withRatios(sum(rows, 'Итого'), cabinetSpend)
}
