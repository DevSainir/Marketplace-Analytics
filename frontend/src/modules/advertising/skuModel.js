/**
 * The per-article table's rows: grouping, filters, totals and the two ratios.
 *
 * Both ratios are re-derived from summed money, never averaged:
 *
 * * **ДРР от продаж** — the seller's own spend (WB's bonus taken off) on
 *   SETTLED days over settled sales. The page's own window may run past the
 *   settlement; those days' spend has no sales to be divided by and stays out
 *   of the numerator (the backend sends it apart as `spend_settled` and
 *   `bonus_settled`).
 * * **Доля** — the row's spend over the кабинет's whole spend for the window,
 *   whatever the filter: «доля общих рекламных расходов».
 */

/** The cuts the table offers; `col` heads the first column, `by` ends the title. */
export const AD_GROUPS = [
  { id: 'sku', name: 'Артикулы', col: 'Артикул', by: 'артикулам' },
  { id: 'subject', name: 'Предметы', col: 'Предмет', by: 'предметам' },
  { id: 'brand', name: 'Бренды', col: 'Бренд', by: 'брендам' },
  { id: 'group', name: 'Группы', col: 'Группа', by: 'группам' },
]

/** The row of articles in none of the groups, as the heatmap names it. */
export const UNGROUPED = 'Без группы'

/** What a missing subject or brand reads as — and groups under. */
const NONE = '—'

const num = (value) => (value === null || value === undefined ? null : Number(value))

/**
 * ДРР as a 0–1 ratio, `null` when there is nothing to divide by.
 *
 * Sales here are net of returns, so a day or an article can come out at zero
 * or below — on «Демо» 19.06.2024 took 101 000 сом of returns against
 * 85 000 of sales. Advertising over a negative sum is a negative ДРР, which
 * means nothing; it is withheld like a day without sales.
 */
export function drrOf(spendSettled, sales) {
  return sales > 0 ? spendSettled / sales : null
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
    bonusSettled: Number(sku.bonus_settled),
    sales: num(sku.sales),
    orders: sku.orders,
    zones: (sku.zones ?? []).map((z) => ({
      zone: z.zone,
      spend: Number(z.spend),
      bonus: Number(z.bonus),
    })),
  }))
}

/** Add one row's zones into a running per-zone sum. */
function mergeZones(acc, zones) {
  const byZone = new Map(acc.map((z) => [z.zone, { ...z }]))
  for (const z of zones) {
    const into = byZone.get(z.zone)
    if (into) {
      into.spend += z.spend
      into.bonus += z.bonus
    } else {
      byZone.set(z.zone, { ...z })
    }
  }
  return [...byZone.values()]
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
 * Rows matching the filters and the search text (article, subject, brand).
 * Several subjects or brands widen a filter; the filters together narrow.
 *
 * @param {object} filters `query`, the chosen `subjects` and `brands`, and
 *   `articles` — the nm_ids of the chosen groups, `null` for no group filter.
 */
export function pickRows(rows, { query = '', subjects = [], brands = [], articles = null }) {
  const needle = query.trim().toLowerCase()
  return rows.filter((row) => {
    if (subjects.length && !subjects.includes(row.subject)) return false
    if (brands.length && !brands.includes(row.brand)) return false
    if (articles && !articles.has(row.nmId)) return false
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
      bonusSettled: acc.bonusSettled + row.bonusSettled,
      sales: addNullable(acc.sales, row.sales),
      orders: addNullable(acc.orders, row.orders),
      zones: mergeZones(acc.zones, row.zones ?? []),
    }),
    {
      label,
      spend: 0,
      bonus: 0,
      spendSettled: 0,
      bonusSettled: 0,
      sales: null,
      orders: null,
      zones: [],
      n: rows.length,
    },
  )
}

/** Attach ДРР and the share of the кабинет's spend. */
function withRatios(row, cabinetSpend) {
  return {
    ...row,
    drr: drrOf(row.spendSettled - row.bonusSettled, row.sales),
    share: cabinetSpend ? row.spend / cabinetSpend : null,
  }
}

/**
 * The same money at the chosen grain, with ratios. A group row carries `n`,
 * the number of articles in it.
 *
 * By «Группы» an article sits in every group it belongs to — the heatmap's
 * rule — and the ones in none share a «Без группы» row. The rows can then add
 * up to more than the кабинет spent, which is why the «Итого» is summed over
 * the articles, never over these rows ({@link totalRow}).
 *
 * @param {Array<{name: string, nm_ids: number[]}>} [groups] For `group` only.
 */
export function groupRows(rows, group, cabinetSpend, groups = []) {
  if (group === 'sku') return rows.map((row) => withRatios(row, cabinetSpend))
  if (group === 'group') return byGroup(rows, groups, cabinetSpend)
  const byKey = new Map()
  for (const row of rows) {
    const key = row[group]
    if (!byKey.has(key)) byKey.set(key, [])
    byKey.get(key).push(row)
  }
  return [...byKey].map(([key, members]) => withRatios(sum(members, key), cabinetSpend))
}

function byGroup(rows, groups, cabinetSpend) {
  const grouped = new Set()
  const out = []
  for (const group of groups) {
    const members = new Set(group.nm_ids)
    const inside = rows.filter((row) => members.has(row.nmId))
    if (!inside.length) continue
    for (const row of inside) grouped.add(row)
    out.push(withRatios(sum(inside, group.name), cabinetSpend))
  }
  const rest = rows.filter((row) => !grouped.has(row))
  if (rest.length) out.push(withRatios(sum(rest, UNGROUPED), cabinetSpend))
  return out
}

/** The «Итого» of the given article rows — the picked ones, not the grouped. */
export function totalRow(rows, cabinetSpend) {
  return withRatios(sum(rows, 'Итого'), cabinetSpend)
}
