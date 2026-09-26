import { describe, expect, it } from 'vitest'

import { hiddenQuantity, limitWarehouses } from '@/modules/labs/stockPivot'

const WAREHOUSES = [
  { name: 'Коледино', total: 500 },
  { name: 'Казань', total: 120 },
  { name: 'Тула', total: 30 },
]

describe('limitWarehouses', () => {
  it('keeps the N fullest and reports the rest as hidden', () => {
    const { shown, hidden } = limitWarehouses(WAREHOUSES, 1)

    expect(shown.map((w) => w.name)).toEqual(['Коледино'])
    expect(hidden.map((w) => w.name)).toEqual(['Казань', 'Тула'])
  })

  it.each([null, 0, -2, '', 'abc', 3, 10])('shows every warehouse for a limit of %p', (limit) => {
    expect(limitWarehouses(WAREHOUSES, limit)).toEqual({ shown: WAREHOUSES, hidden: [] })
  })
})

describe('hiddenQuantity', () => {
  it('sums the row over the folded warehouses so the row still adds up', () => {
    const row = { total: 40, quantities: { Коледино: 25, Казань: 10, Тула: 5 } }
    const { shown, hidden } = limitWarehouses(WAREHOUSES, 1)

    const visible = shown.reduce((sum, w) => sum + (row.quantities[w.name] ?? 0), 0)

    expect(visible + hiddenQuantity(row, hidden)).toBe(row.total)
  })
})
