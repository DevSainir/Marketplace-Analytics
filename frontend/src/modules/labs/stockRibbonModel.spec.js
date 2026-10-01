import { describe, expect, it } from 'vitest'

import {
  HUE_SLOTS,
  LOW_STOCK,
  buildStockRibbon,
  dayParts,
  deltaText,
  deltaTone,
  dotsFor,
  hueVar,
  limitWarehouses,
  plural,
  rowTip,
  stockStatus,
  unitsPerDot,
} from '@/modules/labs/stockRibbonModel'

/**
 * The model the lab's redesigns of «Остатки» draw from. What is pinned here is
 * the arithmetic of MOVEMENT and of the warehouse knob — every variant prints a
 * day-on-day change, and a wrong one would look exactly as plausible as a
 * right one.
 */
const cell = (chrt_id, tech_size, warehouse_name, quantity) => ({
  chrt_id,
  tech_size,
  warehouse_name,
  quantity,
})
const day = (stat_date, cells) => ({ stat_date, stock: { cells } })
const SIZES = [
  { chrt_id: 1, tech_size: 'S' },
  { chrt_id: 2, tech_size: 'M' },
]

describe('buildStockRibbon', () => {
  it('gives the first day no change, because it has no yesterday', () => {
    const days = [day('2026-09-24', [cell(1, 'S', 'Казань', 10)])]

    const [first] = buildStockRibbon(days, SIZES).days

    expect(first.grandDelta).toBeNull()
    expect(first.rows[0].delta).toBeNull()
    expect(first.rows[0].prevTotal).toBeNull()
  })

  it('compares every level with the day before', () => {
    const days = [
      day('2026-09-24', [cell(1, 'S', 'Казань', 10), cell(2, 'M', 'Казань', 4)]),
      day('2026-09-25', [cell(1, 'S', 'Казань', 7), cell(2, 'M', 'Казань', 9)]),
    ]

    const [, second] = buildStockRibbon(days, SIZES).days

    expect(second.grandDelta).toBe(2)
    expect(second.rows[0]).toMatchObject({ total: 7, prevTotal: 10, delta: -3 })
    expect(second.rows[1].segments[0].delta).toBe(5)
  })

  it('names the warehouses that emptied overnight', () => {
    // They drop out of the row, so without this the loss is invisible.
    const days = [
      day('2026-09-24', [cell(1, 'S', 'Казань', 10), cell(1, 'S', 'Тула', 3)]),
      day('2026-09-25', [cell(1, 'S', 'Казань', 9)]),
    ]

    const [, second] = buildStockRibbon(days, SIZES).days

    expect(second.gone).toEqual(['Тула'])
  })

  it('keeps one row per shared size, blank where a day lacks it', () => {
    const days = [day('2026-09-24', [cell(2, 'M', 'Казань', 5)])]

    const [first] = buildStockRibbon(days, SIZES).days

    expect(first.rows).toHaveLength(2)
    expect(first.rows[0]).toMatchObject({ total: 0, status: 'out', segments: [] })
  })

  it('orders and colours segments by period total, not by the day', () => {
    // Тула is fuller on the last day but not over the period: its slice must
    // not jump ahead of Казань there, or the eye loses it between days.
    const days = [
      day('2026-09-24', [cell(1, 'S', 'Казань', 50), cell(1, 'S', 'Тула', 5)]),
      day('2026-09-25', [cell(1, 'S', 'Казань', 4), cell(1, 'S', 'Тула', 8)]),
    ]

    const last = buildStockRibbon(days, SIZES).days[1]

    expect(last.rows[0].segments.map((s) => [s.name, s.hue])).toEqual([
      ['Казань', 0],
      ['Тула', 1],
    ])
  })

  it('folds the warehouses past the palette into one uncoloured tail', () => {
    const names = Array.from({ length: HUE_SLOTS + 2 }, (_, i) => `Склад ${i}`)
    const days = [
      day(
        '2026-09-24',
        names.map((n, i) => cell(1, 'S', n, 100 - i)),
      ),
    ]

    const { warehouses } = buildStockRibbon(days, SIZES)

    expect(warehouses.filter((w) => w.hue === null)).toHaveLength(2)
  })

  it('scales bars to the fullest size of the whole period', () => {
    const days = [
      day('2026-09-24', [cell(1, 'S', 'Казань', 12), cell(1, 'S', 'Тула', 30)]),
      day('2026-09-25', [cell(2, 'M', 'Казань', 41)]),
    ]

    const ribbon = buildStockRibbon(days, SIZES)

    expect(ribbon.maxRow).toBe(42)
    expect(ribbon.sizePeaks).toEqual([42, 41])
  })

  it('counts the sizes a buyer can and cannot get', () => {
    const days = [
      day('2026-09-24', [cell(1, 'S', 'Казань', 3), cell(2, 'M', 'Казань', 9)]),
      day('2026-09-25', [cell(1, 'S', 'Казань', 3)]),
    ]

    const [, second] = buildStockRibbon(days, SIZES).days

    expect(second.counts).toEqual({ in: 0, low: 1, soldOut: 1, out: 0 })
  })
})

describe('limitWarehouses', () => {
  const days = [
    day('2026-09-24', [cell(1, 'S', 'Казань', 10), cell(1, 'S', 'Тула', 30)]),
    day('2026-09-25', [cell(1, 'S', 'Казань', 25), cell(1, 'S', 'Тула', 1)]),
  ]

  it('keeps the fullest warehouses over the period, not over one day', () => {
    const [first] = limitWarehouses(days, 1)

    expect(first.stock.cells.map((c) => c.warehouse_name)).toEqual(['Казань'])
  })

  it('shrinks the totals with it, as a seller with fewer warehouses would see', () => {
    const [first] = buildStockRibbon(limitWarehouses(days, 1), SIZES).days

    expect(first.grandTotal).toBe(10)
  })

  it('leaves the period alone without a limit', () => {
    expect(limitWarehouses(days, null)).toBe(days)
  })
})

describe('stockStatus', () => {
  it('tells «sold out since yesterday» from «never there»', () => {
    expect(stockStatus(0, 4)).toBe('sold-out')
    expect(stockStatus(0, 0)).toBe('out')
  })

  it('calls a size low at the threshold, not above it', () => {
    expect(stockStatus(LOW_STOCK, 0)).toBe('low')
    expect(stockStatus(LOW_STOCK + 1, 0)).toBe('in')
  })
})

describe('dots', () => {
  it('stays one unit a dot while the fullest size fits the row', () => {
    expect(unitsPerDot(60, 60)).toBe(1)
  })

  it('climbs to the next round step once it does not', () => {
    expect(unitsPerDot(61, 60)).toBe(2)
    expect(unitsPerDot(184, 60)).toBe(5)
  })

  it('never rounds a real remainder away', () => {
    expect(dotsFor(1, 5)).toBe(1)
    expect(dotsFor(0, 5)).toBe(0)
  })
})

describe('presentation helpers', () => {
  it('paints a lone warehouse in the action colour', () => {
    expect(hueVar(0, true)).toBe('var(--wh-solo)')
    expect(hueVar(null, false)).toBe('var(--wh-other)')
    expect(hueVar(2, false)).toBe('var(--wh-2)')
  })

  it('signs a change with a real minus', () => {
    expect(deltaText(-1200)).toBe(`−${(1200).toLocaleString('ru-RU')}`)
    expect(deltaText(5)).toBe('+5')
    expect(deltaText(null)).toBe('')
    expect([deltaTone(3), deltaTone(-3), deltaTone(0), deltaTone(null)]).toEqual([
      'up',
      'down',
      'flat',
      null,
    ])
  })

  it('spells out the split only when there is one', () => {
    const one = { total: 7, delta: -2, segments: [{ name: 'Склад WB', q: 7 }] }
    const two = {
      total: 7,
      delta: null,
      segments: [
        { name: 'А', q: 4 },
        { name: 'Б', q: 3 },
      ],
    }

    expect(rowTip('S', one)).toBe('S: 7 шт (−2 за день)')
    expect(rowTip('S', two)).toBe('S: 7 шт · А 4, Б 3')
  })

  it('declines a count the Russian way', () => {
    const word = (n) => plural(n, 'размер', 'размера', 'размеров')

    expect([1, 2, 5, 11, 21, 22, 112].map(word)).toEqual([
      'размер',
      'размера',
      'размеров',
      'размеров',
      'размер',
      'размера',
      'размеров',
    ])
  })

  it('reads the ISO day as the calendar day, whatever the time zone', () => {
    expect(dayParts('2026-09-25')).toMatchObject({
      label: '25.09.2026',
      weekday: 'пт',
      dayMonthLong: '25 сентября',
      weekend: false,
    })
  })
})
