/**
 * The "Stock" grid's arithmetic: the pivot, and the two encodings drawn on it.
 *
 * Extracted from `StockBreakdownTable.vue` when that file reached the 250-line
 * component ceiling. Pure functions over plain data, so they are testable
 * without mounting anything and the component is left holding only its markup.
 */

/**
 * Warehouses ordered by total remaining stock, fullest first (leftmost).
 *
 * @param {Array<{warehouse_name: string, quantity: number}>} cells
 * @returns {Array<{name: string, total: number}>}
 */
export function pivotWarehouses(cells) {
  const totals = new Map()
  for (const cell of cells) {
    totals.set(cell.warehouse_name, (totals.get(cell.warehouse_name) ?? 0) + cell.quantity)
  }
  return (
    [...totals]
      .map(([name, total]) => ({ name, total }))
      // WB reports every seller warehouse, stubs included, so an empty one is a
      // column of zeros — and a column of zeros is not worth the screen space.
      .filter((w) => w.total > 0)
      .sort((a, b) => b.total - a.total || a.name.localeCompare(b.name, 'en'))
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
    labelOf(a).localeCompare(labelOf(b), 'en', { numeric: true }),
  )
}

/**
 * A size's share of the SKU's whole remaining stock, 0..1.
 *
 * Drawn as a bar under the "Total" figure, which turns the frozen column into a
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

/**
 * How many days fit one screen of the ribbon. Two, as in the daily matrix —
 * except for a seller who stocks ONE warehouse (e.g. a single WB warehouse):
 * there a day is one column, "Total" would only repeat it, and two such days
 * stretched across the screen are two numbers per row with a gulf between
 * them, so the ribbon packs five.
 */
export const DAYS_PER_SCREEN = { regular: 2, single: 5 }

/**
 * How many day groups one screen of THIS period holds.
 *
 * Never more than the period has days: a one-day period sized for two left the
 * grid half as wide as its card, with the other half empty. The single-warehouse
 * layout keeps its five regardless — a short period there stays a narrow grid,
 * which is the point of that layout (see above).
 *
 * @param {boolean} single whether the period runs off one warehouse a day
 * @param {number} dayCount days in the period
 * @returns {number}
 */
export function daysPerScreen(single, dayCount) {
  if (single) return DAYS_PER_SCREEN.single
  return Math.max(1, Math.min(DAYS_PER_SCREEN.regular, dayCount))
}

/**
 * Whether the whole period runs off at most one warehouse a day.
 *
 * @param {Array<{warehouses: Array}>} days pivoted days
 * @returns {boolean}
 */
export function isSingleWarehouse(days) {
  return days.some((day) => day.warehouses.length) && days.every((d) => d.warehouses.length <= 1)
}

/**
 * The columns one day renders, left to right. Regular: "Total", then each
 * warehouse the day stocked. Single-warehouse: just that warehouse — or a blank
 * column on a day that held nothing, so every day keeps its place.
 *
 * @param {{warehouses: Array<{name: string, total: number}>}} day
 * @param {boolean} single
 * @returns {Array<{id: string, kind: 'total'|'wh'|'blank', wh?: object}>}
 */
export function dayColumns(day, single) {
  const warehouses = day.warehouses.map((wh) => ({ id: `wh:${wh.name}`, kind: 'wh', wh }))
  if (single) return warehouses.length ? warehouses : [{ id: 'blank', kind: 'blank' }]
  return [{ id: 'total', kind: 'total' }, ...warehouses]
}
