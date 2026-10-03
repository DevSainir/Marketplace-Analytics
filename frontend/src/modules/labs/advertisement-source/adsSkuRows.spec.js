import {
  groupRows,
  pickRows,
  skuAdRows,
  sliceBySku,
  sumRows,
} from '@/modules/labs/advertisement-source/adsSkuRows'

/** A datapack with just the tables the per-SKU half reads. */
function makePack({ skus, pnl = [], orders = [] }) {
  return {
    skus,
    pnl_daily_cols: ['nm_id', 'd', 'revenue', 'card', 'ads'],
    pnl_daily: pnl,
    orders_daily_cols: ['nm_id', 'd', 'orders'],
    orders_daily: orders,
  }
}

const SKU = { code: 'M-A', nm_id: 1, subject: 'Брюки', brand: 'X', ads_hist: { promo: 7 } }

describe('skuAdRows', () => {
  it('weighs ads against the revenue base the reader picked', () => {
    // The same advertising is a larger share of the after-СПП price than of
    // the card price; ДРР must follow the toggle.
    const pack = makePack({ skus: [SKU], pnl: [[1, '2026-08-01', 800, 1000, 100]] })
    const slice = sliceBySku(pack, '2026-08-01', '2026-08-01')

    const [gross] = skuAdRows(pack, slice, 'gross')
    const [card] = skuAdRows(pack, slice, 'card')

    expect(gross.drr).toBeCloseTo(100 / 800)
    expect(card.drr).toBeCloseTo(100 / 1000)
  })

  it('leaves out placeholders and articles with neither ads nor revenue', () => {
    const pack = makePack({
      skus: [
        SKU,
        { code: 'M-IDLE', nm_id: 2, subject: 'Брюки', brand: 'X' },
        { code: 'M-NEW', nm_id: null, subject: 'Брюки', brand: 'X' },
      ],
      pnl: [
        [1, '2026-08-01', 800, 1000, 100],
        [2, '2026-08-01', 0, 0, 0],
      ],
    })
    const slice = sliceBySku(pack, '2026-08-01', '2026-08-01')

    const rows = skuAdRows(pack, slice, 'gross')

    expect(rows.map((r) => r.label)).toEqual(['M-A'])
  })

  it("adds the article's orders from the orders table over the same window", () => {
    const pack = makePack({
      skus: [SKU],
      pnl: [[1, '2026-08-01', 800, 1000, 100]],
      orders: [
        [1, '2026-08-01', 3],
        [1, '2026-08-02', 4],
        [1, '2026-08-09', 99],
      ],
    })
    const slice = sliceBySku(pack, '2026-08-01', '2026-08-07')

    const [row] = skuAdRows(pack, slice, 'gross')

    expect(row.orders).toBe(7)
  })
})

describe('groupRows', () => {
  it("derives a group's ДРР from summed money, not by averaging its articles", () => {
    // A mean of 50 % and 10 % is 30 %; the brand actually spent 60 on 300.
    const rows = [
      { label: 'A', subject: 'Брюки', brand: 'X', ads: 50, revenue: 100, orders: 1, promo: 0 },
      { label: 'B', subject: 'Брюки', brand: 'X', ads: 10, revenue: 200, orders: 2, promo: 5 },
    ]

    const [brand] = groupRows(rows, 'brand')

    expect(brand).toMatchObject({ label: 'X', ads: 60, revenue: 300, orders: 3, promo: 5, n: 2 })
    expect(brand.drr).toBeCloseTo(0.2)
  })
})

describe('sumRows', () => {
  it('has no ДРР, rather than an infinite one, when nothing sold', () => {
    const totals = sumRows([{ ads: 40, revenue: 0, orders: 0, promo: 0 }])

    expect(totals.drr).toBeNull()
  })
})

describe('pickRows', () => {
  it('finds an article by its subject or brand, case-insensitively', () => {
    const rows = [
      { label: 'M-A', subject: 'Брюки', brand: 'X' },
      { label: 'M-B', subject: 'Куртки', brand: 'Y' },
    ]

    const found = pickRows(rows, { query: '  брюки ' })

    expect(found.map((r) => r.label)).toEqual(['M-A'])
  })
})
