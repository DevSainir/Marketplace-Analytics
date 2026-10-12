import { describe, expect, it } from 'vitest'

import { childRows, sortRows, treeRows } from '@/modules/finreports/pnlSkuTree'
import { perSale, sumRows } from '@/modules/finreports/usePnlSkuRows'

const article = (nmId, sales, extra = {}) => ({ nmId, sales, isSku: true, ...extra })

const size = (ts, sold, returned, seller, paid = seller) => ({
  ts_name: ts,
  sold_units: sold,
  returned_units: returned,
  buyout_pct: '50.00',
  revenue_seller_price: String(seller),
  revenue_paid: String(paid),
  logistics_total: '100',
  penalties_total: '0',
  payout_net: '500',
})

const loaded = (rows) => ({ loading: false, error: '', data: { rows } })

describe('sortRows', () => {
  it('orders by the column in either direction', () => {
    const rows = [article(1, 30), article(2, 10), article(3, 20)]

    expect(sortRows(rows, 'sales', 1).map((r) => r.nmId)).toEqual([2, 3, 1])
    expect(sortRows(rows, 'sales', -1).map((r) => r.nmId)).toEqual([1, 3, 2])
  })

  it('keeps an unknown figure last whichever way it sorts', () => {
    const rows = [article(1, null), article(2, 10), article(3, 20)]

    expect(sortRows(rows, 'sales', 1).at(-1).nmId).toBe(1)
    expect(sortRows(rows, 'sales', -1).at(-1).nmId).toBe(1)
  })
})

describe('treeRows', () => {
  it('puts an open article’s sizes right under it, and only its', () => {
    // Arrange
    const page = [article(1, 300), article(2, 100)]
    const sizes = { 1: loaded([size('S', 2, 0, 100), size('M', 4, 0, 200)]) }

    // Act
    const rows = treeRows(page, { 1: true }, sizes, 'seller')

    // Assert
    expect(rows.map((r) => r.rowKey)).toEqual(['a:1', '1:S', '1:M', 'a:2'])
    expect(rows[0].isOpen).toBe(true)
    expect(rows[2].isLast).toBe(true)
  })

  it('shows a loading line, not nothing, while the sizes are on their way', () => {
    const rows = treeRows([article(1, 300)], { 1: true }, {}, 'seller')

    expect(rows[1]).toMatchObject({ kind: 'note', text: 'Загружаем…' })
  })
})

describe('childRows', () => {
  it('gives each size its share of the article for the bars', () => {
    const [s, m] = childRows(1, loaded([size('S', 1, 0, 100), size('M', 3, 0, 300)]), 'seller')

    expect(s.soldShare).toBe(0.25)
    expect(m.salesShare).toBe(0.75)
  })

  it('prices the size’s logistics per unit sold, failed deliveries included', () => {
    // 100 of logistics over 4 sold, whatever the deliveries were.
    const [s] = childRows(1, loaded([size('S', 4, 0, 100)]), 'seller')

    expect(s.logisticsPerSale).toBe(25)
  })

  it('takes «Продажи» and the price at the page’s price base', () => {
    const [s] = childRows(1, loaded([size('S', 3, 1, 1000, 800)]), 'paid')

    expect(s.sales).toBe(800)
    expect(s.averageCheque).toBe(400)
  })
})

describe('«Логистика на 1 выкуп» у артикула и в «Итого»', () => {
  it('делит всю логистику на проданные штуки, а «Итого» — суммы, не средние', () => {
    const a = { logistics: 600, sold: 2, returned: 0, isExcluded: false }
    const b = { logistics: 400, sold: 8, returned: 0, isExcluded: false }

    expect(perSale(600, 2)).toBe(300)
    expect(perSale(600, 0)).toBeNull()
    // 1 000 / 10, а не среднее из 300 и 50.
    expect(sumRows([a, b]).logisticsPerSale).toBe(100)
  })
})
