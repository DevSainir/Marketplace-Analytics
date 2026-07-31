import { subsetDashboard } from '@/modules/finreports/usePnlSkuRows'

/** A raw PnlSkuRow-shaped object (only the fields subsetDashboard reads). */
function row(overrides = {}) {
  return {
    nm_id: 1,
    is_excluded: false,
    sold_units: 10,
    returned_units: 1,
    revenue_paid: '1000',
    sales_amount: '1100',
    returns_amount: '100',
    logistics_total: '200',
    cogs: '300',
    cost_price: '30',
    advertising: '50',
    payout_net: '600',
    ...overrides,
  }
}

describe('subsetDashboard', () => {
  it('sums the visible rows into the dashboard shape', () => {
    const d = subsetDashboard([
      row(),
      row({ nm_id: 2, revenue_paid: '2000', logistics_total: '300' }),
    ])

    expect(d.sales).toBe(3000) // 1000 + 2000
    expect(d.logistics).toBe(500) // 200 + 300
    expect(d.payout_net).toBe(1200) // 600 + 600
    expect(d.logistics_pct).toBeCloseTo((500 / 3000) * 100)
    expect(d.excluded_count).toBe(0)
  })

  it('drops the excluded rows, exactly as the backend dashboard does', () => {
    const d = subsetDashboard([
      row({ revenue_paid: '1000' }),
      row({ nm_id: 2, revenue_paid: '9000', is_excluded: true }),
    ])

    expect(d.sales).toBe(1000) // the excluded 9000 is not counted
    expect(d.excluded_count).toBe(1)
  })

  it('treats a null cost/advertising as absent, not zero-in-the-denominator', () => {
    const d = subsetDashboard([
      row({ cogs: null, cost_price: null, advertising: null, sold_units: 5 }),
    ])

    expect(d.cogs).toBe(0)
    expect(d.other_deductions).toBe(0)
    expect(d.uncosted_count).toBe(1)
  })
})
