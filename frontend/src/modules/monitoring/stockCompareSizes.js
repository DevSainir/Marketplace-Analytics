/**
 * The row set the «Остатки по складам» ribbon shares across its days.
 *
 * The grid renders the UNION of every day's sizes, so each row exists under
 * every day and a size absent from one of them shows blank there rather than
 * shifting the rows below it. One «Размер» column labels the whole period.
 *
 * Pure, and out of the view because the view composes rather than computes —
 * `MonitoringView` is at its 250-line ceiling and this was the piece with the
 * least to do with the page's structure.
 */

/**
 * @param {Array<{stock: ?object}>} days The period's per-day breakdowns.
 * @returns {Array<{chrt_id: number, tech_size: ?string}>} Every day's sizes,
 *   de-duplicated and ordered by their human label.
 */
export function unionStockSizes(days) {
  const byChrt = new Map()
  for (const day of days) {
    for (const cell of day.stock?.cells ?? []) {
      if (!byChrt.has(cell.chrt_id)) byChrt.set(cell.chrt_id, cell.tech_size ?? null)
    }
  }
  const label = (size) => size.tech_size ?? `chrt ${size.chrt_id}`
  return [...byChrt.entries()]
    .map(([chrt_id, tech_size]) => ({ chrt_id, tech_size }))
    .sort((a, b) => label(a).localeCompare(label(b), 'ru', { numeric: true }))
}
