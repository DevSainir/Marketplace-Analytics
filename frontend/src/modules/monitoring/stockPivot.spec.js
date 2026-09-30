import { describe, expect, it } from 'vitest'

import {
  dayColumns,
  daysPerScreen,
  isSingleWarehouse,
  pivotRows,
  pivotWarehouses,
  sizeShare,
} from '@/modules/monitoring/stockPivot'

/**
 * The «Остатки» grid's arithmetic. Pure functions, so they are pinned here
 * rather than through a mounted table — the pivot rules and the two encodings
 * are decisions about the DATA, and none of them needs a DOM to be wrong in.
 */
const cell = (chrt_id, tech_size, warehouse_name, quantity) => ({
  chrt_id,
  tech_size,
  warehouse_name,
  quantity,
})

const label = (row) => row.tech_size ?? `chrt ${row.chrt_id}`

describe('pivotWarehouses', () => {
  it('puts the fullest warehouse leftmost', () => {
    const cells = [cell(1, 'S', 'Коледино', 5), cell(1, 'S', 'Казань', 40)]

    const result = pivotWarehouses(cells)

    expect(result.map((w) => w.name)).toEqual(['Казань', 'Коледино'])
  })

  it('drops a warehouse holding nothing', () => {
    // WB reports every seller warehouse, stubs included, so an empty one would
    // otherwise cost a column of zeros on a grid that is already too wide.
    const cells = [cell(1, 'S', 'Пустой', 0), cell(1, 'S', 'Казань', 7)]

    const result = pivotWarehouses(cells)

    expect(result.map((w) => w.name)).toEqual(['Казань'])
  })

  it('breaks a tie on stock by name', () => {
    const cells = [cell(1, 'S', 'Тула', 4), cell(1, 'S', 'Казань', 4)]

    const result = pivotWarehouses(cells)

    expect(result.map((w) => w.name)).toEqual(['Казань', 'Тула'])
  })
})

describe('pivotRows', () => {
  it('sums a size across warehouses', () => {
    const cells = [cell(1, 'S', 'Казань', 4), cell(1, 'S', 'Коледино', 6)]

    const [row] = pivotRows(cells, null, label)

    expect(row.total).toBe(10)
    expect(row.quantities).toEqual({ Казань: 4, Коледино: 6 })
  })

  it('keeps clothing sizes in wear order, not lexical order', () => {
    // '122' sorts before '42' as text; a size list that reads 122, 42, 44 is
    // the sort nobody wants.
    const cells = [cell(3, '122', 'A', 1), cell(1, '42', 'A', 1), cell(2, '44', 'A', 1)]

    const rows = pivotRows(cells, null, label)

    expect(rows.map(label)).toEqual(['42', '44', '122'])
  })

  it('renders an imposed size the day never stocked as a blank row', () => {
    // Comparison mode: both days must show identical rows or the two tables
    // cannot be read across.
    const cells = [cell(1, 'S', 'A', 5)]

    const rows = pivotRows(
      cells,
      [
        { chrt_id: 1, tech_size: 'S' },
        { chrt_id: 2, tech_size: 'M' },
      ],
      label,
    )

    expect(rows.map((r) => r.total)).toEqual([5, 0])
    expect(rows[1].quantities).toEqual({})
  })
})

describe('sizeShare', () => {
  it('is the size’s share of the whole remaining stock', () => {
    expect(sizeShare(25, 100)).toBe(0.25)
  })

  it('is zero for a depleted size', () => {
    expect(sizeShare(0, 100)).toBe(0)
  })

  it('is safe when nothing is in stock at all', () => {
    expect(sizeShare(0, 0)).toBe(0)
  })
})

describe('the single-warehouse layout', () => {
  const day = (...names) => ({ warehouses: names.map((name) => ({ name, total: 1 })) })

  it('applies when no day holds more than one warehouse', () => {
    expect(isSingleWarehouse([day('Коледино'), day(), day('Коледино')])).toBe(true)
  })

  it('does not apply once any day holds two', () => {
    expect(isSingleWarehouse([day('Коледино'), day('Коледино', 'Казань')])).toBe(false)
  })

  it('does not apply to a period with no stock at all', () => {
    expect(isSingleWarehouse([day(), day()])).toBe(false)
  })

  it('drops «Всего» and keeps an empty day as one blank column', () => {
    expect(dayColumns(day('Коледино'), true).map((c) => c.kind)).toEqual(['wh'])
    expect(dayColumns(day(), true).map((c) => c.kind)).toEqual(['blank'])
  })

  it('leads a regular day with «Всего»', () => {
    expect(dayColumns(day('Коледино', 'Казань'), false).map((c) => c.kind)).toEqual([
      'total',
      'wh',
      'wh',
    ])
  })
})

describe('daysPerScreen', () => {
  it('fits two days a screen', () => {
    expect(daysPerScreen(false, 30)).toBe(2)
  })

  it('gives a one-day period the whole screen, not half of it', () => {
    expect(daysPerScreen(false, 1)).toBe(1)
  })

  it('keeps five for one warehouse, however short the period', () => {
    expect(daysPerScreen(true, 1)).toBe(5)
  })
})
