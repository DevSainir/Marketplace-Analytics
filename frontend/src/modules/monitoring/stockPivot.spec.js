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
 * The "Stock" grid's arithmetic. Pure functions, so they are pinned here
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
    const cells = [cell(1, 'S', 'Koledino', 5), cell(1, 'S', 'Kazan', 40)]

    const result = pivotWarehouses(cells)

    expect(result.map((w) => w.name)).toEqual(['Kazan', 'Koledino'])
  })

  it('drops a warehouse holding nothing', () => {
    // WB reports every seller warehouse, stubs included, so an empty one would
    // otherwise cost a column of zeros on a grid that is already too wide.
    const cells = [cell(1, 'S', 'Elektrostal', 0), cell(1, 'S', 'Kazan', 7)]

    const result = pivotWarehouses(cells)

    expect(result.map((w) => w.name)).toEqual(['Kazan'])
  })

  it('breaks a tie on stock by name', () => {
    const cells = [cell(1, 'S', 'Tula', 4), cell(1, 'S', 'Kazan', 4)]

    const result = pivotWarehouses(cells)

    expect(result.map((w) => w.name)).toEqual(['Kazan', 'Tula'])
  })
})

describe('pivotRows', () => {
  it('sums a size across warehouses', () => {
    const cells = [cell(1, 'S', 'Kazan', 4), cell(1, 'S', 'Koledino', 6)]

    const [row] = pivotRows(cells, null, label)

    expect(row.total).toBe(10)
    expect(row.quantities).toEqual({ Kazan: 4, Koledino: 6 })
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
    expect(isSingleWarehouse([day('Koledino'), day(), day('Koledino')])).toBe(true)
  })

  it('does not apply once any day holds two', () => {
    expect(isSingleWarehouse([day('Koledino'), day('Koledino', 'Kazan')])).toBe(false)
  })

  it('does not apply to a period with no stock at all', () => {
    expect(isSingleWarehouse([day(), day()])).toBe(false)
  })

  it('drops "Total" and keeps an empty day as one blank column', () => {
    expect(dayColumns(day('Koledino'), true).map((c) => c.kind)).toEqual(['wh'])
    expect(dayColumns(day(), true).map((c) => c.kind)).toEqual(['blank'])
  })

  it('leads a regular day with "Total"', () => {
    expect(dayColumns(day('Koledino', 'Kazan'), false).map((c) => c.kind)).toEqual([
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
