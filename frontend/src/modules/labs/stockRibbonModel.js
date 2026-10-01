/**
 * The «Остатки» ribbon as the three design variants read it.
 *
 * The original grid (`StockCompareTable.vue`) pivots each day on its own and
 * never looks at the day before. All three variants below it draw MOVEMENT —
 * a delta badge, a flashing cell, a shrinking bar — so they share one model
 * that pivots every day AND compares it with its predecessor. Pure, so it is
 * tested without mounting anything.
 *
 * The pivot itself is `stockPivot.js`'s, not a second copy: «which warehouses
 * a day shows» and «what a size's total is» must not mean something different
 * one table lower on the same page.
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
 * palette minus its green and red, which here already mean «приход» and «расход».
 * A seventh hue is never generated — the tail folds into
 * one neutral «прочие» instead (`hue: null`).
 */
export const HUE_SLOTS = 6

/** Steps of the heat scale, not counting «empty». */
export const HEAT_STEPS = 6

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
 * A cell's step on the heat scale, 0 (empty) to `steps`.
 *
 * Square-root, not linear: a seller's stock is two Moscow hubs and a long tail,
 * and on a linear scale every tail cell lands in step one — the scale would say
 * «big» and «nothing» and nothing in between.
 */
export function heatLevel(quantity, max, steps = HEAT_STEPS) {
  if (!quantity || quantity <= 0 || !max) return 0
  return Math.min(steps, Math.max(1, Math.ceil(Math.sqrt(quantity / max) * steps)))
}

/**
 * Ticker-style three-letter codes: «Коледино» → «КОЛ». A collision takes the
 * first letter of the name's second word, then its last letter, then a digit —
 * «Краснодар»/«Красноярск» must not both read «КРА».
 */
export function warehouseCodes(names) {
  const codes = new Map()
  const taken = new Set()
  for (const name of names) {
    const words = name.toUpperCase().match(/[A-ZА-ЯЁ0-9]+/g) ?? ['?']
    const first = words[0]
    const candidates = [
      first.slice(0, 3),
      words[1] ? first.slice(0, 2) + words[1][0] : null,
      first.slice(0, 2) + first.at(-1),
    ].filter(Boolean)
    let code = candidates.find((c) => !taken.has(c))
    for (let n = 2; !code; n += 1) {
      if (!taken.has(`${first.slice(0, 2)}${n}`)) code = `${first.slice(0, 2)}${n}`
    }
    taken.add(code)
    codes.set(name, code)
  }
  return codes
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
 *   maxCell: number,
 *   warehouses: Array<{name: string, code: string, hue: ?number, max: number}>,
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
  // the WHOLE period take the colours, so a column keeps its hue as it moves.
  const periodTotals = new Map()
  const columnMax = new Map()
  let maxCell = 0
  for (const day of pivoted) {
    for (const wh of day.warehouses) {
      periodTotals.set(wh.name, (periodTotals.get(wh.name) ?? 0) + wh.total)
    }
    for (const row of day.rows) {
      for (const [name, q] of Object.entries(row.quantities)) {
        maxCell = Math.max(maxCell, q)
        columnMax.set(name, Math.max(columnMax.get(name) ?? 0, q))
      }
    }
  }
  const ranked = [...periodTotals]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'ru'))
    .map(([name]) => name)
  const codes = warehouseCodes(ranked)
  const identity = new Map(
    ranked.map((name, i) => [
      name,
      { name, code: codes.get(name), hue: i < HUE_SLOTS ? i : null, max: columnMax.get(name) },
    ]),
  )

  const model = pivoted.map((day, d) => {
    const prev = d > 0 ? pivoted[d - 1] : null
    const prevWh = prev ? new Map(prev.warehouses.map((w) => [w.name, w.total])) : null
    const grandTotal = day.warehouses.reduce((sum, w) => sum + w.total, 0)
    const prevGrand = prev?.warehouses.reduce((sum, w) => sum + w.total, 0)
    const stocked = new Set(day.warehouses.map((w) => w.name))
    return {
      key: day.iso,
      ...dayParts(day.iso),
      newest: d === pivoted.length - 1,
      grandTotal,
      // The fullest size's total — what a bar scaled to the day's curve tops out at.
      peak: Math.max(0, ...day.rows.map((row) => row.total)),
      grandDelta: deltaOf(grandTotal, prevGrand, Boolean(prev)),
      warehouses: day.warehouses.map((w) => ({
        ...identity.get(w.name),
        total: w.total,
        delta: deltaOf(w.total, prevWh?.get(w.name), Boolean(prev)),
        share: sizeShare(w.total, grandTotal),
      })),
      // Stocked yesterday, empty today — the column that silently vanished.
      gone: prev ? prev.warehouses.filter((w) => !stocked.has(w.name)).map((w) => w.name) : [],
      rows: day.rows.map((row, r) => {
        const before = prev?.rows[r]
        const cells = {}
        for (const w of day.warehouses) {
          const q = row.quantities[w.name] ?? 0
          cells[w.name] = { q, delta: deltaOf(q, before?.quantities[w.name], Boolean(before)) }
        }
        return {
          total: row.total,
          delta: deltaOf(row.total, before?.total, Boolean(before)),
          share: sizeShare(row.total, grandTotal),
          cells,
        }
      }),
    }
  })

  return {
    days: model,
    sizes: sizeOrder.map((s) => ({ chrt_id: s.chrt_id, label: sizeLabel(s) })),
    maxCell,
    warehouses: [...identity.values()],
  }
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

/** A day-on-day change as a percentage of yesterday, or `null` without one. */
export function deltaPercent(today, delta) {
  const yesterday = today - (delta ?? 0)
  if (delta === null || delta === undefined || yesterday <= 0) return null
  return (delta / yesterday) * 100
}
