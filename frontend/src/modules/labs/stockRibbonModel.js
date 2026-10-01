/**
 * The «Остатки» ribbon as the lab's redesigns read it.
 *
 * The original grid gives every warehouse a COLUMN. That is the right shape
 * for fifteen warehouses and the wrong one for what a seller sees since WB
 * folded its report into one «Склад WB» on 16.08 (`wildberries-api` skill,
 * `references/stocks.md`): one column per day, two days across a 1300px
 * screen, and a gulf between two numbers per row. So here a warehouse is not
 * a column but a SEGMENT inside its size's row — a slice of a bar, a run of
 * dots, a stripe on a chip — and a size row means the same thing whether one
 * warehouse feeds it or fifteen.
 *
 * Each day is also compared with the day before, because what the team reads
 * is the movement. Pure, so it is tested without mounting anything; the pivot
 * itself is `stockPivot.js`'s, so «a size's total» cannot mean something
 * different one table lower on the same page.
 */
import { pivotRows, pivotWarehouses, sizeShare } from '@/modules/labs/stockPivot'

import { formatNumber } from '@/core/utils/format'

const WEEKDAYS = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб']
const WEEKDAYS_LONG = [
  'воскресенье',
  'понедельник',
  'вторник',
  'среда',
  'четверг',
  'пятница',
  'суббота',
]
const MONTHS = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
const MONTHS_LONG = [
  'января',
  'февраля',
  'марта',
  'апреля',
  'мая',
  'июня',
  'июля',
  'августа',
  'сентября',
  'октября',
  'ноября',
  'декабря',
]

/**
 * How many warehouses get a colour of their own: the validated categorical
 * palette minus its green and red, which here already mean «приход» and
 * «расход». A seventh hue is never generated — the tail folds into one
 * neutral «прочие» instead (`hue: null`).
 */
export const HUE_SLOTS = 6

/**
 * At or under this many units a size counts as running out. Absolute rather
 * than relative: a size that never held more than four is still four units
 * from gone, whatever its own history says.
 */
export const LOW_STOCK = 5

/** Human size label (WB «Размер вещи»), or the raw id until the catalogue syncs. */
export function sizeLabel(size) {
  return size.tech_size ?? `chrt ${size.chrt_id}`
}

/**
 * "2026-09-25" → its calendar parts. Read in UTC: the ISO day IS the day, and
 * a local-time parse would move it across midnight west of Greenwich.
 */
export function dayParts(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  const weekday = new Date(Date.UTC(y, m - 1, d)).getUTCDay()
  return {
    label: `${String(d).padStart(2, '0')}.${String(m).padStart(2, '0')}.${y}`,
    weekday: WEEKDAYS[weekday],
    weekdayLong: WEEKDAYS_LONG[weekday],
    dayMonth: `${d} ${MONTHS[m - 1]}`,
    dayMonthLong: `${d} ${MONTHS_LONG[m - 1]}`,
    weekend: weekday === 0 || weekday === 6,
  }
}

/**
 * LAB-ONLY debug knob: the period as a seller with `limit` warehouses would
 * see it — the `limit` fullest over the whole period, every other
 * warehouse's cells dropped. Unlike the original grid's knob, which hides
 * columns and keeps «Всего» whole, totals here shrink with it: a seller with
 * one warehouse has no stock anywhere else to add up.
 *
 * @param {Array<{stat_date: string, stock: ?{cells: object[]}}>} days
 * @param {?number} limit `null` = every warehouse
 */
export function limitWarehouses(days, limit) {
  if (!limit) return days
  const totals = new Map()
  for (const day of days) {
    for (const cell of day.stock?.cells ?? []) {
      totals.set(cell.warehouse_name, (totals.get(cell.warehouse_name) ?? 0) + cell.quantity)
    }
  }
  const kept = new Set(
    [...totals]
      .filter(([, total]) => total > 0)
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'ru'))
      .slice(0, limit)
      .map(([name]) => name),
  )
  return days.map((day) => ({
    ...day,
    stock: day.stock && {
      ...day.stock,
      cells: day.stock.cells.filter((cell) => kept.has(cell.warehouse_name)),
    },
  }))
}

/**
 * Where a size stands today: `out` (nothing, nor yesterday), `sold-out`
 * (something yesterday, nothing today — the one to act on), `low` (at or under
 * `LOW_STOCK`) or `in`.
 */
export function stockStatus(total, prevTotal) {
  if (total <= 0) return prevTotal > 0 ? 'sold-out' : 'out'
  return total <= LOW_STOCK ? 'low' : 'in'
}

/** `today - yesterday`, or `null` on the first day, which has no yesterday. */
function deltaOf(today, yesterday, hasYesterday) {
  return hasYesterday ? today - (yesterday ?? 0) : null
}

/**
 * @param {Array<{stat_date: string, stock: ?{cells: object[]}}>} days oldest first
 * @param {Array<{chrt_id: number, tech_size: ?string}>} sizeOrder the shared row set
 * @returns {{
 *   days: object[],
 *   sizes: Array<{chrt_id: number, label: string}>,
 *   warehouses: Array<{name: string, hue: ?number}>,
 *   maxRow: number,
 *   sizePeaks: number[],
 * }}
 */
export function buildStockRibbon(days, sizeOrder) {
  const pivoted = days.map((day) => {
    const cells = day.stock?.cells ?? []
    return {
      iso: day.stat_date,
      warehouses: pivotWarehouses(cells),
      rows: pivotRows(cells, sizeOrder, sizeLabel),
    }
  })

  // Identity follows the warehouse, never its rank on the day: the fullest over
  // the WHOLE period take the colours AND the order, so a warehouse keeps its
  // hue and its place in every row as the days go by.
  const periodTotals = new Map()
  for (const day of pivoted) {
    for (const wh of day.warehouses) {
      periodTotals.set(wh.name, (periodTotals.get(wh.name) ?? 0) + wh.total)
    }
  }
  const warehouses = [...periodTotals]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'ru'))
    .map(([name], i) => ({ name, hue: i < HUE_SLOTS ? i : null }))

  const sizePeaks = sizeOrder.map((_, r) =>
    Math.max(0, ...pivoted.map((day) => day.rows[r]?.total ?? 0)),
  )

  const model = pivoted.map((day, d) => {
    const prev = d > 0 ? pivoted[d - 1] : null
    const totals = new Map(day.warehouses.map((w) => [w.name, w.total]))
    const prevTotals = prev ? new Map(prev.warehouses.map((w) => [w.name, w.total])) : null
    const grandTotal = day.warehouses.reduce((sum, w) => sum + w.total, 0)
    const prevGrand = prev?.warehouses.reduce((sum, w) => sum + w.total, 0)

    const rows = day.rows.map((row, r) => {
      const before = prev?.rows[r]
      const prevTotal = before ? before.total : null
      return {
        total: row.total,
        prevTotal,
        delta: deltaOf(row.total, prevTotal, Boolean(before)),
        status: stockStatus(row.total, prevTotal ?? 0),
        segments: warehouses
          .filter((w) => row.quantities[w.name] > 0)
          .map((w) => ({
            ...w,
            q: row.quantities[w.name],
            delta: deltaOf(row.quantities[w.name], before?.quantities[w.name], Boolean(before)),
          })),
      }
    })

    return {
      key: day.iso,
      ...dayParts(day.iso),
      newest: d === pivoted.length - 1,
      grandTotal,
      grandDelta: deltaOf(grandTotal, prevGrand, Boolean(prev)),
      warehouses: warehouses
        .filter((w) => totals.has(w.name))
        .map((w) => ({
          ...w,
          total: totals.get(w.name),
          delta: deltaOf(totals.get(w.name), prevTotals?.get(w.name), Boolean(prev)),
          share: sizeShare(totals.get(w.name), grandTotal),
        })),
      // Stocked yesterday, empty today — a warehouse that silently left the row.
      gone: prev ? prev.warehouses.filter((w) => !totals.has(w.name)).map((w) => w.name) : [],
      counts: {
        in: rows.filter((row) => row.status === 'in').length,
        low: rows.filter((row) => row.status === 'low').length,
        soldOut: rows.filter((row) => row.status === 'sold-out').length,
        out: rows.filter((row) => row.status === 'out').length,
      },
      rows,
    }
  })

  return {
    days: model,
    sizes: sizeOrder.map((s) => ({ chrt_id: s.chrt_id, label: sizeLabel(s) })),
    warehouses,
    maxRow: Math.max(0, ...sizePeaks),
    sizePeaks,
  }
}

/** The ladder `unitsPerDot` climbs: one unit a dot for as long as that fits. */
const DOT_STEPS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]

/**
 * How many units one dot stands for, so the fullest size of the period fits
 * `capacity` dots. The smallest step that fits — «поштучно» stays literal for
 * as long as the numbers allow it.
 */
export function unitsPerDot(maxRow, capacity) {
  return DOT_STEPS.find((step) => Math.ceil(maxRow / step) <= capacity) ?? DOT_STEPS.at(-1)
}

/** Units → dots at `per` a dot; any real remainder is at least one dot. */
export function dotsFor(units, per) {
  if (units <= 0) return 0
  return Math.max(1, Math.round(units / per))
}

/** «+56» / «−120» (a real minus, not a hyphen) / «0»; empty on the first day. */
export function deltaText(delta) {
  if (delta === null || delta === undefined) return ''
  if (delta === 0) return '0'
  return `${delta > 0 ? '+' : '−'}${formatNumber(Math.abs(delta))}`
}

/** Which way a delta points, for the class that colours it. */
export function deltaTone(delta) {
  if (delta === null || delta === undefined) return null
  return delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat'
}

/**
 * One size, spelled out for a tooltip: the figure, the day's change and —
 * when more than one warehouse feeds it — the split.
 */
export function rowTip(label, row) {
  const change = row.delta ? ` (${deltaText(row.delta)} за день)` : ''
  const head = row.total ? `${label}: ${formatNumber(row.total)} шт${change}` : `${label}: нет`
  if (row.segments.length < 2) return head
  return `${head} · ${row.segments.map((s) => `${s.name} ${formatNumber(s.q)}`).join(', ')}`
}

/**
 * The CSS colour a warehouse paints with. A period fed by ONE warehouse paints
 * in the action violet: with nothing to tell apart, a categorical blue would
 * only say «this is a category» about a thing that has no siblings.
 */
export function hueVar(hue, solo) {
  if (solo) return 'var(--wh-solo)'
  return hue === null ? 'var(--wh-other)' : `var(--wh-${hue})`
}

/** Russian plural: `plural(1, 'размер', 'размера', 'размеров')` → «размер». */
export function plural(n, one, few, many) {
  const tens = n % 100
  const units = n % 10
  if (tens >= 11 && tens <= 14) return many
  if (units === 1) return one
  return units >= 2 && units <= 4 ? few : many
}
