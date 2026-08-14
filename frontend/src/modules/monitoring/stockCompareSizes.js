/**
 * The row set the two-day stock comparison shares.
 *
 * Both side-by-side tables render the UNION of the two days' sizes so their rows
 * align 1:1 (a size absent on one day shows blank there). Each table still
 * carries its own «Размер» column, so the labels repeat by design: it keeps each
 * day readable on its own, and the pair still compares row by row.
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
