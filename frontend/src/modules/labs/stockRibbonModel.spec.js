import { describe, expect, it } from 'vitest'

import {
  HUE_SLOTS,
  buildStockRibbon,
  dayParts,
  deltaPercent,
  deltaText,
  deltaTone,
  heatLevel,
  warehouseCodes,
} from '@/modules/labs/stockRibbonModel'

/**
 * The model the three lab redesigns of «Остатки» draw from. What is pinned
 * here is the arithmetic of MOVEMENT — every variant prints a day-on-day change,
 * and a wrong delta would look exactly as plausible as a right one.
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
    expect(first.warehouses[0].delta).toBeNull()
    expect(first.rows[0].cells['Казань'].delta).toBeNull()
  })

  it('compares every level with the day before', () => {
    const days = [
      day('2026-09-24', [cell(1, 'S', 'Казань', 10), cell(2, 'M', 'Казань', 4)]),
      day('2026-09-25', [cell(1, 'S', 'Казань', 7), cell(2, 'M', 'Казань', 9)]),
    ]

    const [, second] = buildStockRibbon(days, SIZES).days

    expect(second.grandDelta).toBe(2)
    expect(second.warehouses[0].delta).toBe(2)
    expect(second.rows[0].cells['Казань'].delta).toBe(-3)
    expect(second.rows[1].delta).toBe(5)
  })

  it('counts a warehouse new today as a change from zero', () => {
    const days = [
      day('2026-09-24', [cell(1, 'S', 'Казань', 10)]),
      day('2026-09-25', [cell(1, 'S', 'Казань', 10), cell(1, 'S', 'Тула', 6)]),
    ]

    const [, second] = buildStockRibbon(days, SIZES).days

    expect(second.warehouses.find((w) => w.name === 'Тула').delta).toBe(6)
  })

  it('names the warehouses that emptied overnight', () => {
    // They drop out of today's columns, so without this the loss is invisible.
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
    expect(first.rows[0].total).toBe(0)
    expect(first.rows[0].cells['Казань'].q).toBe(0)
  })

  it('colours warehouses by period total, not by their rank on one day', () => {
    // Тула is fullest on the last day but not over the period: its hue must not
    // jump to slot 0 there, or the eye loses it from one card to the next.
    const days = [
      day('2026-09-24', [cell(1, 'S', 'Казань', 50), cell(1, 'S', 'Тула', 5)]),
      day('2026-09-25', [cell(1, 'S', 'Казань', 4), cell(1, 'S', 'Тула', 8)]),
    ]

    const ribbon = buildStockRibbon(days, SIZES)
    const last = ribbon.days[1]

    expect(last.warehouses.map((w) => w.name)).toEqual(['Тула', 'Казань'])
    expect(last.warehouses.find((w) => w.name === 'Казань').hue).toBe(0)
    expect(last.warehouses.find((w) => w.name === 'Тула').hue).toBe(1)
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

  it('reports the period’s fullest cell for the heat scale', () => {
    const days = [
      day('2026-09-24', [cell(1, 'S', 'Казань', 12), cell(2, 'M', 'Тула', 30)]),
      day('2026-09-25', [cell(1, 'S', 'Казань', 41)]),
    ]

    expect(buildStockRibbon(days, SIZES).maxCell).toBe(41)
  })
})

describe('heatLevel', () => {
  it('leaves an empty cell at step zero', () => {
    expect(heatLevel(0, 100)).toBe(0)
  })

  it('puts any real remainder at step one or above', () => {
    expect(heatLevel(1, 1000)).toBe(1)
  })

  it('tops out at the fullest cell', () => {
    expect(heatLevel(100, 100)).toBe(6)
  })

  it('spreads the tail out on a square-root scale', () => {
    // Linear, a quarter of the max would sit in step two; the root lifts it to
    // three, which is what keeps the tail from collapsing into one shade.
    expect(heatLevel(25, 100)).toBe(3)
  })
})

describe('warehouseCodes', () => {
  it('takes the first three letters', () => {
    expect(warehouseCodes(['Коледино']).get('Коледино')).toBe('КОЛ')
  })

  it('never hands two warehouses the same code', () => {
    const names = ['Краснодар', 'Красноярск', 'Красный Бор', 'Крас']

    const codes = [...warehouseCodes(names).values()]

    expect(new Set(codes).size).toBe(names.length)
  })
})

describe('day-on-day text', () => {
  it('signs a change with a real minus', () => {
    expect(deltaText(-1200)).toBe(`−${(1200).toLocaleString('ru-RU')}`)
    expect(deltaText(5)).toBe('+5')
  })

  it('prints nothing on the day with no yesterday', () => {
    expect(deltaText(null)).toBe('')
    expect(deltaTone(null)).toBeNull()
  })

  it('names the direction', () => {
    expect([deltaTone(3), deltaTone(-3), deltaTone(0)]).toEqual(['up', 'down', 'flat'])
  })

  it('gives the change as a share of yesterday', () => {
    expect(deltaPercent(110, 10)).toBe(10)
    expect(deltaPercent(5, 5)).toBeNull()
  })
})

describe('dayParts', () => {
  it('reads the ISO day as the calendar day, whatever the time zone', () => {
    expect(dayParts('2026-09-25')).toMatchObject({
      label: '25.09.2026',
      weekday: 'пт',
      dayMonthLong: '25 сентября',
      weekend: false,
    })
  })
})
