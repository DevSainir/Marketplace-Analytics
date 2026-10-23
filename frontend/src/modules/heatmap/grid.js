/**
 * The heatmap grid's presentation rules: column captions, the order rows are
 * shown in, the page on screen, and the tint of each cell.
 *
 * Pure functions over the backend's payload — no figure is computed here, only
 * arranged. Sorting and paging live on this side of the wire on purpose: the
 * payload already carries every row of the selection, so a header click or a
 * page flip is instant instead of a round trip over the whole window.
 */
import { MONTHS, formatDayShort, weekdayOf } from '@/core/utils/calendarWords'
import { heatStyle, scaleAround, scaleOf } from '@/modules/heatmap/heatScale'
import { addsUp } from '@/modules/heatmap/metrics'

/**
 * The caption of one column: "Wed 23 Sep", "21–27 Sep" (or "28 Sep–4 Oct"
 * across two months), "September 2026".
 *
 * @param {{start: string, end: string}} column
 * @param {'day'|'week'|'month'} period
 * @returns {string}
 */
export function columnLabel(column, period) {
  if (period === 'day') return `${weekdayOf(column.start)} ${formatDayShort(column.start)}`
  if (period === 'month') {
    const [year, month] = column.start.split('-')
    return `${MONTHS[Number(month) - 1]} ${year}`
  }
  const [first, last] = [formatDayShort(column.start), formatDayShort(column.end)]
  const [day, month] = first.split(' ')
  return last.endsWith(` ${month}`) ? `${day}–${last}` : `${first}–${last}`
}

/**
 * Rows in the order the seller asked for. Empty cells always sink to the
 * bottom, whichever way the column is sorted — a row with nothing to show is
 * never the answer to "who is best" or "who is worst".
 *
 * @param {Array<object>} rows As the backend sends them (already ranked by orders).
 * @param {{by: 'total'|number|null, dir: 'asc'|'desc'}} sort `by` is a column
 *   index, `'total'` for "Total", or `null` for the backend's own order.
 * @returns {Array<object>}
 */
export function sortRows(rows, sort) {
  if (sort.by === null || sort.by === undefined) return rows
  const read = (row) => (sort.by === 'total' ? row.total : row.values[sort.by])
  const sign = sort.dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const left = read(a)
    const right = read(b)
    if (left === null && right === null) return 0
    if (left === null) return 1
    if (right === null) return -1
    return (left - right) * sign
  })
}

/**
 * One page of rows, and how many pages there are.
 *
 * @param {Array<object>} rows
 * @param {number} page 1-based.
 * @param {number} size Rows per page.
 */
export function pageOf(rows, page, size) {
  const pages = Math.max(1, Math.ceil(rows.length / size))
  const current = Math.min(Math.max(1, page), pages)
  return { rows: rows.slice((current - 1) * size, current * size), page: current, pages }
}

const DAY_MS = 86_400_000

/**
 * Days in each column — a week or month clipped by the window is shorter.
 *
 * @param {Array<{start: string, end: string}>} columns
 * @returns {number[]}
 */
export function columnDays(columns) {
  return columns.map(({ start, end }) => (Date.parse(end) - Date.parse(start)) / DAY_MS + 1)
}

/**
 * Tints for every cell of the rows on screen.
 *
 * "By row" measures each row against its own norm (the median of its days);
 * "Whole table" measures every row against the norm of the whole
 * SELECTION — not only this page — so turning the page does not quietly change
 * what green means. The "Total" column and row are not painted: they are the
 * yardstick, not a sample.
 *
 * With `normOf`, a row that has a hand-set norm is painted against it instead.
 * The norm is per day, so a metric that adds up is compared per day too — a
 * week's 350 orders against a norm of 50 is on the norm — and the extremes come
 * from the same per-day values, of the row or of the whole selection.
 *
 * @param {Array<object>} pageRows The rows being drawn.
 * @param {Array<object>} allRows Every row of the selection.
 * @param {'row'|'table'} mode
 * @param {{key: string, direction: 'up'|'down'|'neutral'}} metric The painted metric.
 * @param {{columns?: Array<object>, normOf?: (row: object) => number|null}} [manual]
 * @returns {Array<Array<object>>} One array of cell styles per row.
 */
export function tintRows(pageRows, allRows, mode, metric, { columns = [], normOf = null } = {}) {
  const paint = (values, scale) => values.map((value) => heatStyle(value, scale, metric.direction))
  const table = mode === 'table' ? scaleOf(allRows.flatMap((row) => row.values)) : null
  const days = columnDays(columns)
  const daily = (values) =>
    addsUp(metric) ? values.map((value, i) => (value === null ? null : value / days[i])) : values
  let dailyTable = null
  return pageRows.map((row) => {
    const norm = normOf?.(row) ?? null
    if (norm === null) return paint(row.values, table ?? scaleOf(row.values))
    if (mode === 'table') dailyTable ??= allRows.flatMap((other) => daily(other.values))
    const values = daily(row.values)
    return paint(values, scaleAround(mode === 'table' ? dailyTable : values, norm))
  })
}

/**
 * The monitoring page for one article over the same window.
 *
 * @param {number} nmId
 * @param {string} from
 * @param {string} to
 */
export function monitoringLink(nmId, from, to) {
  return { name: 'monitoring', query: { sku: String(nmId), date_from: from, date_to: to } }
}

/** @param {number} nmId */
export function storefrontUrl(nmId) {
  return `https://www.wildberries.ru/catalog/${nmId}/detail.aspx`
}
