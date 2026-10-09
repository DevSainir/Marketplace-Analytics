import { UNGROUPED, groupRows, pickRows, toRows, totalRow } from '@/modules/advertising/skuModel'

const SKUS = [
  {
    vendor_code: 'M-A',
    nm_id: 1,
    subject: 'Брюки',
    brand: 'X',
    spend: '50',
    bonus: '5',
    spend_settled: '50',
    bonus_settled: '0',
    sales: '100',
    orders: 1,
  },
  {
    vendor_code: 'M-B',
    nm_id: 2,
    subject: 'Брюки',
    brand: 'X',
    spend: '30',
    bonus: '0',
    spend_settled: '10',
    bonus_settled: '0',
    sales: '200',
    orders: 2,
  },
]

describe('groupRows', () => {
  it("derives a group's ДРР from summed settled money, not by averaging its articles", () => {
    // A mean of 50 % and 5 % is 27,5 %; the brand actually spent 60 against 300 of sales.
    const [brand] = groupRows(toRows(SKUS), 'brand', 400)

    expect(brand).toMatchObject({ label: 'X', spend: 80, spendSettled: 60, sales: 300, n: 2 })
    expect(brand.drr).toBeCloseTo(0.2)
  })

  it("measures a row's share against the кабинет's whole spend, not the filtered table", () => {
    const [first] = groupRows(toRows(SKUS), 'sku', 400)

    expect(first.share).toBeCloseTo(50 / 400)
  })
})

describe('totalRow', () => {
  it('keeps ДРР unknown while nothing has settled, rather than infinite', () => {
    const rows = toRows(SKUS.map((s) => ({ ...s, sales: null })))

    expect(totalRow(rows, 80).drr).toBeNull()
  })
})

describe('ДРР от продаж', () => {
  it("is the seller's own money over sales — WB's bonus comes off the spend", () => {
    // 50 spent, 20 of it paid by WB, against 100 of sales: the seller paid 30%.
    const [row] = groupRows(
      toRows([{ ...SKUS[0], spend_settled: '50', bonus_settled: '20', sales: '100' }]),
      'sku',
      50,
    )

    expect(row.drr).toBeCloseTo(0.3)
  })

  it('is withheld when returns outweighed sales, rather than negative', () => {
    // «Демо», 19.06.2024: 1 520 of advertising, sales net of returns −14 870.
    const [row] = groupRows(
      toRows([{ ...SKUS[0], spend_settled: '1520', sales: '-14870' }]),
      'sku',
      1520,
    )

    expect(row.drr).toBeNull()
  })
})

describe('the zone breakdown of a group', () => {
  it("sums its articles' zones, zone by zone", () => {
    const rows = toRows([
      { ...SKUS[0], zones: [{ zone: 'cpm_manual_search', spend: '50', bonus: '5' }] },
      {
        ...SKUS[1],
        zones: [
          { zone: 'cpm_manual_search', spend: '20', bonus: '0' },
          { zone: 'cpm_unified_shelves', spend: '10', bonus: '0' },
        ],
      },
    ])

    const [brand] = groupRows(rows, 'brand', 80)

    expect(brand.zones).toEqual([
      { zone: 'cpm_manual_search', spend: 70, bonus: 5 },
      { zone: 'cpm_unified_shelves', spend: 10, bonus: 0 },
    ])
  })
})

describe('by «Группы»', () => {
  const third = { ...SKUS[0], vendor_code: 'M-C', nm_id: 3, brand: 'Y', spend: '20' }
  const rows = toRows([...SKUS, third])
  const groups = [
    { id: 'a', name: 'Лето', nm_ids: [1, 2] },
    { id: 'b', name: 'Хиты', nm_ids: [2] },
    { id: 'c', name: 'Пустая', nm_ids: [99] },
  ]

  it('puts an article in every group it is in, and the rest under «Без группы»', () => {
    const out = groupRows(rows, 'group', 100, groups)

    expect(out.map((r) => [r.label, r.n, r.spend])).toEqual([
      ['Лето', 2, 80],
      ['Хиты', 1, 30],
      [UNGROUPED, 1, 20],
    ])
  })

  it('totals the articles, not the overlapping group rows', () => {
    // The group rows add up to 130; the кабинет spent 100.
    expect(totalRow(rows, 100).spend).toBe(100)
  })
})

describe('pickRows', () => {
  const rows = toRows([...SKUS, { ...SKUS[0], vendor_code: 'M-C', nm_id: 3, brand: 'Y' }])
  const labels = (filters) => pickRows(rows, filters).map((r) => r.label)

  it('widens within a filter and narrows across them', () => {
    expect(labels({ brands: ['X', 'Y'] })).toEqual(['M-A', 'M-B', 'M-C'])
    expect(labels({ brands: ['X', 'Y'], articles: new Set([2, 3]) })).toEqual(['M-B', 'M-C'])
    expect(labels({ subjects: ['Шорты'] })).toEqual([])
  })

  it('treats no articles as no group filter, and an empty set as one that matches nothing', () => {
    expect(labels({ articles: null })).toHaveLength(3)
    expect(labels({ articles: new Set() })).toEqual([])
  })
})
