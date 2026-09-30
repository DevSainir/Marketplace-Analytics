/**
 * Arranging the heatmap: captions, row order, paging and which scale a cell is
 * painted against.
 *
 * The sort rule is the one worth pinning: a row with no value in the sorted
 * column must never surface as the best or the worst — it has nothing to say.
 */
import { columnDays, columnLabel, pageOf, sortRows, tintRows } from './grid'

const row = (key, values, total = null) => ({ key, values, total })

describe('columnLabel', () => {
  it('names a day with its weekday', () => {
    expect(columnLabel({ start: '2026-09-23', end: '2026-09-23' }, 'day')).toBe('23.09 (ср)')
  })

  it('names a week by its first and last day', () => {
    expect(columnLabel({ start: '2026-09-21', end: '2026-09-27' }, 'week')).toBe('21.09–27.09')
  })

  it('names a month in words', () => {
    expect(columnLabel({ start: '2026-09-01', end: '2026-09-30' }, 'month')).toBe('Сентябрь 2026')
  })
})

describe('sortRows', () => {
  const rows = [row('a', [5]), row('b', [null]), row('c', [9])]

  it('keeps the backend order until a column is chosen', () => {
    expect(sortRows(rows, { by: null, dir: 'desc' }).map((r) => r.key)).toEqual(['a', 'b', 'c'])
  })

  it('sinks empty cells to the bottom when sorting down', () => {
    expect(sortRows(rows, { by: 0, dir: 'desc' }).map((r) => r.key)).toEqual(['c', 'a', 'b'])
  })

  it('sinks empty cells to the bottom when sorting up too', () => {
    expect(sortRows(rows, { by: 0, dir: 'asc' }).map((r) => r.key)).toEqual(['a', 'c', 'b'])
  })

  it('sorts by the row total', () => {
    const totals = [row('a', [], 1), row('b', [], 3)]
    expect(sortRows(totals, { by: 'total', dir: 'desc' }).map((r) => r.key)).toEqual(['b', 'a'])
  })
})

describe('pageOf', () => {
  it('clamps a page past the end to the last one', () => {
    const rows = Array.from({ length: 45 }, (_, i) => row(String(i), []))
    const page = pageOf(rows, 9, 30)
    expect(page.page).toBe(2)
    expect(page.pages).toBe(2)
    expect(page.rows).toHaveLength(15)
  })
})

describe('tintRows', () => {
  const orders = { direction: 'up' }

  it("paints a dip against the row's own median", () => {
    const dip = row('dip', [100, 104, 30, 101, 99])
    const [tints] = tintRows([dip], [dip], 'row', orders)
    expect(tints[2].background).toContain('--ui-neg-rgb')
    expect(tints[0].background).toBeUndefined()
  })

  it('puts every row on one norm in table mode, not just the page', () => {
    const quiet = row('quiet', [10, 11, 10])
    const busy = [1, 2, 3].map((n) => row(`busy${n}`, [100, 104, 98]))
    const [tints] = tintRows([quiet], [quiet, ...busy], 'table', orders)
    expect(tints[0].background).toContain('--ui-neg-rgb')
  })
})

describe('tintRows with hand-set norms', () => {
  const orders = { key: 'orders', direction: 'up' }
  const week = { start: '2026-09-21', end: '2026-09-27' }
  const day = { start: '2026-09-28', end: '2026-09-28' }

  it('counts the days of a clipped column', () => {
    expect(columnDays([week, day])).toEqual([7, 1])
  })

  it('compares a week of a summed metric with the daily norm times its days', () => {
    const r = { ...row('r', [350, 30]), nm_id: 1 }
    const [tints] = tintRows([r], [r], 'row', orders, { columns: [week, day], normOf: () => 50 })
    expect(tints[0]).toEqual({})
    expect(tints[1].background).toContain('--ui-neg-rgb')
  })

  it('compares a ratio as it is, whatever the column width', () => {
    const r = { ...row('r', [2, 3]), nm_id: 1 }
    const ctr = { key: 'ctr', direction: 'up' }
    const [tints] = tintRows([r], [r], 'row', ctr, { columns: [week, day], normOf: () => 2 })
    expect(tints[0]).toEqual({})
    expect(tints[1].background).toContain('--ui-pos-rgb')
  })

  it('keeps the median for a row with no norm of its own', () => {
    const r = { ...row('r', [100, 104, 30]), nm_id: 1 }
    const cols = [day, day, day]
    const [tints] = tintRows([r], [r], 'row', orders, { columns: cols, normOf: () => null })
    expect(tints[0]).toEqual({})
  })
})
