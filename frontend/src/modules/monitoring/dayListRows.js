/**
 * The metrics matrix projected as a LIST — one day at a time, for a phone.
 *
 * The table is 10 traffic columns per day and cannot be narrowed into a 402pt
 * screen by any amount of column work: sized to fit, each column lands around
 * 10px and the numbers print over one another; sized to their content, one day
 * runs several screens wide and the reader swipes through mostly-empty campaign
 * zones to reach the totals. A phone reads one day at a time, so that is what
 * this projects — metric on the left, that day's "Overall" value on the right,
 * and the traffic split folded away behind a disclosure for the metrics that
 * have one worth opening.
 *
 * It reads the SAME `row.cells` the table renders, addressed the same way:
 * one matrix, projected two ways, never two sources of truth. Pure, so it is
 * testable without mounting anything.
 */
import { weekdayOf } from '@/core/utils/calendarWords'
import {
  DRR_SALES_COLUMNS,
  TRAFFIC_COLUMNS,
  TRAFFIC_GROUPS,
} from '@/modules/monitoring/metricsMatrix'

const COLUMNS_PER_DAY = TRAFFIC_COLUMNS.length

/** "Overall" is every metric's headline — the whole day, all traffic. */
const TOTAL_OFFSET = TRAFFIC_COLUMNS.findIndex((column) => column.key === 'total')

/**
 * One label per leaf column: "Unified bid · Search" for the zoned groups,
 * the bare group name for "Overall"/"Organic", which have no zone split.
 */
const LEAF_LABELS = TRAFFIC_GROUPS.flatMap((group, groupIndex) => {
  const offset = TRAFFIC_GROUPS.slice(0, groupIndex).reduce((sum, g) => sum + g.span, 0)
  return TRAFFIC_COLUMNS.slice(offset, offset + group.span).map((column) =>
    group.spansZones ? group.label : `${group.label} · ${column.zone}`,
  )
})

const LEAF_BREAKDOWN = LEAF_LABELS.map((label, offset) => ({ label, offset }))

/**
 * Rows that do not lay out every leaf column, and so break down differently:
 * "ACoS (sales)" is a CAMPAIGN-level number (one per traffic group), and
 * "Buyout rate" is one number for the whole day — nothing to break down.
 */
const BREAKDOWN_OVERRIDES = {
  drr_sales: DRR_SALES_COLUMNS.map((column, index) => ({
    label: TRAFFIC_GROUPS[index].label,
    offset: column.offset,
  })),
  buyout_percent: null,
}

/**
 * The metric rows of one day.
 *
 * @param {Array<{key, label, tone, emphasis, cells: object[]}>} rows
 * @param {number} dayIndex
 * @returns {Array<{key, label, tone, emphasis, cell, breakdown}>} `breakdown` is
 *   null when there is nothing behind the headline worth opening.
 */
export function metricDayItems(rows, dayIndex) {
  const base = dayIndex * COLUMNS_PER_DAY

  return rows.map((row) => {
    const columns = row.key in BREAKDOWN_OVERRIDES ? BREAKDOWN_OVERRIDES[row.key] : LEAF_BREAKDOWN
    const breakdown = (columns ?? []).map((column) => ({
      label: column.label,
      offset: column.offset,
      cell: row.cells[base + column.offset] ?? null,
    }))

    return {
      key: row.key,
      label: row.label,
      tone: row.tone ?? null,
      emphasis: Boolean(row.emphasis),
      cell: row.cells[base + TOTAL_OFFSET] ?? null,
      // A split that only restates the headline is noise on a phone: offer the
      // disclosure only once a column OTHER than "Overall" carries a number.
      breakdown: breakdown.some((entry) => entry.offset !== TOTAL_OFFSET && entry.cell?.raw != null)
        ? breakdown
        : null,
    }
  })
}

/**
 * The "Prices"/"Stock" block rows of one day.
 *
 * These carry one cell per DAY rather than one per traffic column (they only
 * ever have "Overall"-bucket values), so they are indexed differently and have
 * no breakdown at all.
 */
export function blockDayItems(rows, dayIndex) {
  return rows.map((row) => ({
    key: row.key,
    label: row.label,
    tone: row.tone ?? null,
    emphasis: false,
    cell: row.cells[dayIndex] ?? null,
    breakdown: null,
  }))
}

/**
 * "Sun, 19 Jul 2026" — the weekday matters when paging a day at a time, because
 * weekends are the first thing anyone checks a demand dip against.
 *
 * The weekday comes from the ISO parts (`weekdayOf`), never from the browser's
 * zone: `new Date(iso)` parses a bare date string as UTC and lands on the
 * previous day west of Greenwich.
 */
export function dayLabelWithWeekday(day) {
  if (!day) return ''
  return `${weekdayOf(day.iso)}, ${day.label}`
}
