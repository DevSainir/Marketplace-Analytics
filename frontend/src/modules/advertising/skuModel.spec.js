import { groupRows, toRows, totalRow } from '@/modules/advertising/skuModel'

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
})
