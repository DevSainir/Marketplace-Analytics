/**
 * The balance grid's view logic: order, filtering, and the two totals panels.
 *
 * Everything the backend does NOT decide lives here, and that is deliberate: a
 * «Не считать» and a search both change the order and every total the moment
 * they are clicked, with no round trip. So the column order, the row order and
 * all three panels are computed from the priced cells the response carries plus
 * the mark sets, which the store keeps optimistically ahead of the server.
 *
 * The arithmetic is only ADDITION over backend-priced cells — the balance math
 * itself (units x cost price) stays on the backend, where the cost prices are.
 */
import { computed, ref } from 'vue'

import { formatMoney, formatSku } from '@/core/utils/format'
import { useSkuFilters } from '@/modules/finreports/skuFilters'
import { splitBy, useGroupCut } from '@/modules/heatmap'

const num = (value) => (value === null || value === undefined ? null : Number(value))

/** Warehouse names longer than this are shortened; hover reveals the full one. */
export const NAME_LIMIT = 8

/**
 * A money formatter bound to the response's currency, e.g. 57600 -> «57 600с».
 * Missing money (an uncosted SKU) stays an em dash — a blank balance and a zero
 * balance mean different things on a table whose whole subject is money.
 */
export function moneyFormatter(currency) {
  return (value) => (value === null || value === undefined ? '—' : formatMoney(value, currency))
}

/**
 * Compact warehouse header: WB names like «Электросталь» blow a numeric column
 * up, so only the first {@link NAME_LIMIT} letters are shown and the full name
 * comes back on hover.
 */
export function shortWarehouseName(name) {
  return name.length > NAME_LIMIT ? `${name.slice(0, NAME_LIMIT)}…` : name
}

/**
 * Flatten one backend balance row, totalling it over the COUNTED warehouses.
 *
 * The row's «По остаткам» and «По себестоимости» are deliberately not the same
 * population: the units are what is lying in the warehouses (what can ship
 * today), the money is that plus the goods in transit (what the seller has
 * already paid for). «В пути» beside them is what reconciles the two.
 *
 * @param {object} r The backend row.
 * @param {Set<string>} uncounted Warehouses marked «Не считать».
 * @param {Set<number>} uncountedSkus SKUs marked «Не считать».
 */
export function toRow(r, uncounted, uncountedSkus) {
  const byWarehouse = {}
  let totalQuantity = 0
  let totalInWay = 0
  let totalBalance = 0
  for (const cell of r.cells ?? []) {
    // A cell is what is LYING in that warehouse, units and money alike — the
    // grid and «Итого по складу» beneath it answer «what is on this shelf».
    // Goods in transit belong to no shelf, so they are collected here for the
    // row's own summary and never written into a cell.
    const balance = num(cell.balance)
    byWarehouse[cell.warehouse_name] = { quantity: cell.quantity, balance }
    if (uncounted.has(cell.warehouse_name)) continue
    totalQuantity += cell.quantity
    totalInWay += cell.in_way ?? 0
    totalBalance += (balance ?? 0) + (num(cell.in_way_balance) ?? 0)
  }
  return {
    nmId: r.nm_id,
    saName: formatSku(r.sa_name),
    subject: r.subject_name || '',
    brand: r.brand_name || '',
    costPrice: num(r.cost_price),
    isUncounted: uncountedSkus.has(r.nm_id),
    byWarehouse,
    totalQuantity,
    totalInWay,
    // An uncosted SKU has no balance at all — 0 would read as «free goods».
    totalBalance: r.cost_price === null || r.cost_price === undefined ? null : totalBalance,
  }
}

/**
 * Sum the visible rows into the panels — «Итого по складу» and the corner.
 *
 * A column marked «Не считать» keeps its OWN total (the seller wants to see
 * what is lying there) but contributes nothing to the corner. A ROW marked the
 * same way keeps its «Итого по артикулу» and contributes to neither: it is out
 * of the count on both axes, which is the whole point of the mark.
 *
 * The two outputs answer different questions and their money does not tie out,
 * by design: `warehouses` is per SHELF and holds only what is lying on it,
 * while the corner is the seller's whole holding and carries the goods in
 * transit too. `inWay` in the corner is what accounts for the difference.
 *
 * @param {Array<object>} rows Flattened rows currently on screen.
 * @param {Array<{name: string, isUncounted: boolean}>} columns The grid's
 *   columns, kept in full even when a filter empties one — a column that
 *   disappears while typing makes the grid jump under the reader.
 */
export function subtotals(rows, columns) {
  const perWarehouse = new Map(columns.map((c) => [c.name, { quantity: 0, balance: 0 }]))
  let quantity = 0
  let inWay = 0
  let balance = 0
  for (const row of rows) {
    if (row.isUncounted) continue
    quantity += row.totalQuantity
    inWay += row.totalInWay
    balance += row.totalBalance ?? 0
    for (const [name, cell] of Object.entries(row.byWarehouse)) {
      const total = perWarehouse.get(name)
      if (!total) continue
      total.quantity += cell.quantity
      total.balance += cell.balance ?? 0
    }
  }
  return {
    warehouses: columns.map((c) => ({ ...c, ...perWarehouse.get(c.name) })),
    quantity,
    inWay,
    balance,
  }
}

/**
 * The grid's rows by subject, brand or group: each one the sum of its
 * articles, warehouse by warehouse. Like the panels, a sum leaves out the
 * articles marked «Не считать» — they are out of every count — and a bucket of
 * nothing but marked ones has no row. By group an article counts in every
 * group it is in.
 *
 * @param {Array<object>} rows Flattened rows from {@link toRow}.
 * @param {'subject'|'brand'|'group'} cut
 * @param {Array<object>} groups The workspace's «Группы».
 */
export function groupBalanceRows(rows, cut, groups) {
  const how = { nmId: (r) => r.nmId, subject: (r) => r.subject, brand: (r) => r.brand, groups }
  return splitBy(rows, cut, how)
    .map(({ key, label, items }) => {
      const counted = items.filter((r) => !r.isUncounted)
      if (!counted.length) return null
      const byWarehouse = {}
      for (const row of counted) {
        for (const [name, cell] of Object.entries(row.byWarehouse)) {
          const into = (byWarehouse[name] ??= { quantity: 0, balance: null })
          into.quantity += cell.quantity
          if (cell.balance !== null) into.balance = (into.balance ?? 0) + cell.balance
        }
      }
      const money = counted.filter((r) => r.totalBalance !== null)
      return {
        nmId: key,
        saName: label,
        isGroup: true,
        n: items.length,
        subject: '',
        brand: '',
        costPrice: null,
        isUncounted: false,
        byWarehouse,
        totalQuantity: counted.reduce((sum, r) => sum + r.totalQuantity, 0),
        totalInWay: counted.reduce((sum, r) => sum + r.totalInWay, 0),
        // Unknown only when no article of it has a cost price — see `toRow`.
        totalBalance: money.length ? money.reduce((sum, r) => sum + r.totalBalance, 0) : null,
      }
    })
    .filter(Boolean)
}

/**
 * Search + «Тип предмета» / «Бренд» filtering over one loaded balance response.
 *
 * @param {import('vue').Ref<object|null>} balance The `/finreports/balance` payload.
 */
export function useBalanceRows(balance) {
  const query = ref('')
  const { subjectFilter, brandFilter, groupFilter, active, apply } = useSkuFilters()
  const cut = ref('sku')
  const { groups, readable: groupsReadable } = useGroupCut(cut)

  const rawRows = computed(() => balance.value?.rows ?? [])
  const uncounted = computed(() => new Set(balance.value?.uncounted_warehouses ?? []))
  const uncountedSkus = computed(() => new Set(balance.value?.uncounted_skus ?? []))

  /**
   * The columns: every warehouse holding stock today, «Не считать» ones last,
   * the rest by how much stock they hold.
   */
  const columns = computed(() => {
    const quantities = new Map()
    for (const row of rawRows.value) {
      for (const cell of row.cells ?? []) {
        // Ordered on the shelf alone, which is what these columns show — a
        // column ranked on figures it does not display reads as mis-sorted.
        quantities.set(
          cell.warehouse_name,
          (quantities.get(cell.warehouse_name) ?? 0) + cell.quantity,
        )
      }
    }
    return [...quantities]
      .map(([name, stock]) => ({
        name,
        isUncounted: uncounted.value.has(name),
        stock,
      }))
      .sort(
        (a, b) =>
          a.isUncounted - b.isUncounted || b.stock - a.stock || a.name.localeCompare(b.name, 'ru'),
      )
  })

  const distinct = (key) =>
    [...new Set(rawRows.value.map((r) => r[key]).filter(Boolean))].sort((a, b) =>
      a.localeCompare(b, 'ru'),
    )
  // «Тип предмета» and «Бренд» have no column of their own here (the grid's columns
  // are warehouses), but they stay filterable — they are how a seller narrows a
  // catalogue down to the part they are actually restocking.
  const subjects = computed(() => distinct('subject_name'))
  const brands = computed(() => distinct('brand_name'))

  const isFiltering = computed(() => !!query.value.trim() || active.value)

  /** One row per article — what the panels sum, whatever the cut. */
  const articleRows = computed(() => {
    const needle = query.value.trim().toLowerCase()
    let list = rawRows.value
    list = apply(list)
    if (needle) {
      list = list.filter((r) =>
        [r.sa_name, String(r.nm_id), r.subject_name, r.brand_name].some((field) =>
          field?.toLowerCase().includes(needle),
        ),
      )
    }
    // «Не считается» rows trail, and the rest keep the backend's «largest
    // balance first» — the same two groups the columns fall into, one axis over.
    return list
      .map((r) => toRow(r, uncounted.value, uncountedSkus.value))
      .sort((a, b) => a.isUncounted - b.isUncounted)
  })

  /** What the grid shows: the articles, or their sums by the chosen cut. */
  const tableRows = computed(() =>
    cut.value === 'sku'
      ? articleRows.value
      : groupBalanceRows(articleRows.value, cut.value, groups.value),
  )

  /**
   * The bottom «Итого по складу» panel and the bottom-right corner — over the
   * articles, not the rows: by group one article can sit in two rows.
   */
  const totals = computed(() => subtotals(articleRows.value, columns.value))

  // The columns fall into two contiguous groups — ordinary and «не считается» —
  // so the header can title each one and a rule can sit on the seam. The rows
  // have one seam of the same kind.
  const uncountedCount = computed(() => columns.value.filter((c) => c.isUncounted).length)
  const uncountedRowCount = computed(() => tableRows.value.filter((r) => r.isUncounted).length)
  const isGroupBoundary = (index) =>
    index > 0 && uncountedCount.value > 0 && index === columns.value.length - uncountedCount.value
  const isRowBoundary = (index) =>
    index > 0 &&
    uncountedRowCount.value > 0 &&
    index === tableRows.value.length - uncountedRowCount.value

  return {
    query,
    subjectFilter,
    brandFilter,
    groupFilter,
    cut,
    groupsReadable,
    subjects,
    brands,
    columns,
    tableRows,
    totals,
    isFiltering,
    uncountedCount,
    isGroupBoundary,
    isRowBoundary,
  }
}
