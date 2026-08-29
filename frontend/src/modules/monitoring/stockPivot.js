/**
 * The «Остатки» grid's arithmetic: the pivot, and the two encodings drawn on it.
 *
 * Extracted from `StockBreakdownTable.vue` when that file reached the 250-line
 * component ceiling. Pure functions over plain data, so they are testable
 * without mounting anything and the component is left holding only its markup.
 */

/**
 * Warehouses ordered by total remaining stock, fullest first (leftmost) —
 * except marked ones, which always come before every unmarked one and are
 * sorted by stock only among themselves.
 *
 * @param {Array<{warehouse_name: string, quantity: number}>} cells
 * @param {Set<string>} markedSet names of warehouses marked «на отгрузку»
 * @returns {Array<{name: string, total: number, marked: boolean}>}
 */
export function pivotWarehouses(cells, markedSet) {
  const totals = new Map()
  for (const cell of cells) {
    totals.set(cell.warehouse_name, (totals.get(cell.warehouse_name) ?? 0) + cell.quantity)
  }
  return (
    [...totals]
      .map(([name, total]) => ({ name, total, marked: markedSet.has(name) }))
      // WB reports every seller warehouse, stubs included, so an empty one is a
      // column of zeros. A MARKED one stays: «we ship there and it is empty».
      .filter((w) => w.total > 0 || w.marked)
      .sort(
        (a, b) => b.marked - a.marked || b.total - a.total || a.name.localeCompare(b.name, 'ru'),
      )
  )
}

/**
 * One row per size, each carrying its per-warehouse quantities and its total.
 *
 * @param {Array<object>} cells `StockDetail.cells` for one day
 * @param {Array<{chrt_id: number, tech_size: string}>|null} sizeOrder imposed
 *   row set (comparison mode): identical rows on both sides, a size this day
 *   never stocked renders blank
 * @param {(row: object) => string} labelOf human size label, for sorting
 * @returns {Array<{chrt_id: number, tech_size: string, total: number, quantities: object}>}
 */
export function pivotRows(cells, sizeOrder, labelOf) {
  const byChrt = new Map()
  for (const cell of cells) {
    let row = byChrt.get(cell.chrt_id)
    if (!row) {
      row = { chrt_id: cell.chrt_id, tech_size: cell.tech_size, total: 0, quantities: {} }
      byChrt.set(cell.chrt_id, row)
    }
    row.quantities[cell.warehouse_name] = (row.quantities[cell.warehouse_name] ?? 0) + cell.quantity
    row.total += cell.quantity
  }
  if (sizeOrder) {
    return sizeOrder.map(
      (size) =>
        byChrt.get(size.chrt_id) ?? {
          chrt_id: size.chrt_id,
          tech_size: size.tech_size,
          total: 0,
          quantities: {},
        },
    )
  }
  // `numeric` keeps clothing sizes in wear order (42 < 44 < 122).
  return [...byChrt.values()].sort((a, b) =>
    labelOf(a).localeCompare(labelOf(b), 'ru', { numeric: true }),
  )
}

/**
 * A size's share of the SKU's whole remaining stock, 0..1.
 *
 * Drawn as a bar under the «Всего» figure, which turns the frozen column into a
 * size-distribution read at a glance: whether the stock is spread across the
 * curve or piled on the two sizes nobody buys.
 *
 * @param {number} total the size's total
 * @param {number} grandTotal every size's total
 * @returns {number} 0..1
 */
export function sizeShare(total, grandTotal) {
  if (!total || grandTotal <= 0) return 0
  return Math.min(total / grandTotal, 1)
}
