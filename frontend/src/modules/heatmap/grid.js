/**
 * The heatmap grid's presentation rules: column captions, the order rows are
 * shown in, the page on screen, and the tint of each cell.
 *
 * Pure functions over the backend's payload — no figure is computed here, only
 * arranged. Sorting and paging live on this side of the wire on purpose: the
 * payload already carries every row of the selection, so a header click or a
 * page flip is instant instead of a round trip over the whole window.
 */
import { MONTHS } from '@/core/utils/calendarModel'
import {
  departure,
  heatStyle,
  normOf,
  rangeOf,
  rangePosition,
  rangeStyle,
} from '@/modules/heatmap/heatScale'

const WEEKDAYS = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб']

/** "2026-09-23" → "23.09". */
function dayMonth(iso) {
  const [, month, day] = iso.split('-')
  return `${day}.${month}`
}

/**
 * The caption of one column: «23.09 (ср)», «15.09–21.09», «Сентябрь 2026».
 *
 * @param {{start: string, end: string}} column
 * @param {'day'|'week'|'month'} period
 * @returns {string}
 */
export function columnLabel(column, period) {
  if (period === 'day') {
    const weekday = WEEKDAYS[new Date(`${column.start}T12:00:00`).getDay()]
    return `${dayMonth(column.start)} (${weekday})`
  }
  if (period === 'month') {
    const [year, month] = column.start.split('-')
    return `${MONTHS[Number(month) - 1]} ${year}`
  }
  return `${dayMonth(column.start)}–${dayMonth(column.end)}`
}

/**
 * Rows in the order the seller asked for. Empty cells always sink to the
 * bottom, whichever way the column is sorted — a row with nothing to show is
 * never the answer to «кто лучше» or «кто хуже».
 *
 * @param {Array<object>} rows As the backend sends them (already ranked by orders).
 * @param {{by: 'total'|number|null, dir: 'asc'|'desc'}} sort `by` is a column
 *   index, `'total'` for «Итого», or `null` for the backend's own order.
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

/**
 * Tints for every cell of the rows on screen.
 *
 * «Дни одного товара» measures each row against its own norm (the median of
 * its days); «товары между собой» measures every row against the norm of the
 * whole SELECTION — not only this page — so turning the page does not quietly
 * change what green means. The «Итого» column and row are not painted: they
 * are the yardstick, not a sample.
 *
 * @param {Array<object>} pageRows The rows being drawn.
 * @param {Array<object>} allRows Every row of the selection.
 * @param {'row'|'table'} mode
 * @param {{direction: 'up'|'down'|'neutral', unit: string, band?: number}} metric
 *   The painted metric.
 * @returns {Array<Array<object>>} One array of cell styles per row.
 */
export function tintRows(pageRows, allRows, mode, metric) {
  const options = { count: metric.unit === 'count', band: metric.band }
  const table = mode === 'table' ? normOf(allRows.flatMap((row) => row.values)) : null
  return pageRows.map((row) => {
    const norm = table ?? normOf(row.values)
    return row.values.map((value) => heatStyle(departure(value, norm, options), metric.direction))
  })
}

/**
 * The same tints on the range scale — worst to best of the compared cells —
 * for the second, comparison table. Same modes, same «Итого» rule.
 *
 * @param {Array<object>} pageRows
 * @param {Array<object>} allRows
 * @param {'row'|'table'} mode
 * @param {{direction: 'up'|'down'|'neutral'}} metric
 * @returns {Array<Array<object>>}
 */
export function rangeTintRows(pageRows, allRows, mode, metric) {
  const table = mode === 'table' ? rangeOf(allRows.flatMap((row) => row.values)) : null
  return pageRows.map((row) => {
    const range = table ?? rangeOf(row.values)
    return row.values.map((value) =>
      rangeStyle(rangePosition(value, range, metric.direction), metric.direction),
    )
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
