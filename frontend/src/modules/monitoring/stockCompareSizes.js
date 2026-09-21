/**
 * The row set the two-day stock comparison shares.
 *
 * The single grid renders the UNION of the two days' sizes, so every row exists
 * under both days and a size absent from one of them shows blank there rather
 * than shifting the rows below it. One «Размер» column labels the pair.
 *
 * Pure, and out of the view because the view composes rather than computes —
 * `MonitoringView` is at its 250-line ceiling and this was the piece with the
 * least to do with the page's structure.
 */

/**
 * @param {{left: {stock: ?object}, right: {stock: ?object}}} compare The store's
 *   two-day comparison state.
 * @returns {Array<{chrt_id: number, tech_size: ?string}>} Sizes of both days,
 *   de-duplicated and ordered by their human label.
 */
export function unionStockSizes(compare) {
  const byChrt = new Map()
  for (const side of ['left', 'right']) {
    for (const cell of compare[side].stock?.cells ?? []) {
      if (!byChrt.has(cell.chrt_id)) byChrt.set(cell.chrt_id, cell.tech_size ?? null)
    }
  }
  const label = (size) => size.tech_size ?? `chrt ${size.chrt_id}`
  return [...byChrt.entries()]
    .map(([chrt_id, tech_size]) => ({ chrt_id, tech_size }))
    .sort((a, b) => label(a).localeCompare(label(b), 'ru', { numeric: true }))
}
