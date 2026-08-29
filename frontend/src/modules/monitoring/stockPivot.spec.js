import { describe, expect, it } from 'vitest'

import { pivotRows, pivotWarehouses, sizeShare } from '@/modules/monitoring/stockPivot'

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

    const result = pivotWarehouses(cells, new Set())

    expect(result.map((w) => w.name)).toEqual(['Казань', 'Коледино'])
  })

  it('drops an empty warehouse but keeps an empty MARKED one', () => {
    // WB reports every seller warehouse, stubs included. A marked one that is
    // empty is the whole point of marking it: «we ship there and it is empty».
    const cells = [cell(1, 'S', 'Пустой', 0), cell(1, 'S', 'Отгружаем', 0)]

    const result = pivotWarehouses(cells, new Set(['Отгружаем']))

    expect(result.map((w) => w.name)).toEqual(['Отгружаем'])
  })

  it('sorts every marked warehouse ahead of every unmarked one', () => {
    const cells = [cell(1, 'S', 'Большой', 900), cell(1, 'S', 'Мелкий', 3)]

    const result = pivotWarehouses(cells, new Set(['Мелкий']))

    expect(result.map((w) => w.name)).toEqual(['Мелкий', 'Большой'])
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
