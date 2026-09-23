import { subsetDashboard, sumRows } from '@/modules/finreports/usePnlSkuRows'

/** A raw PnlSkuRow-shaped object (only the fields subsetDashboard reads). */
function row(overrides = {}) {
  return {
    nm_id: 1,
    is_excluded: false,
    sold_units: 10,
    returned_units: 1,
    revenue_seller_price: '1000',
    revenue_paid: '900',
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
      row({ nm_id: 2, revenue_seller_price: '2000', revenue_paid: '1800', logistics_total: '300' }),
    ])

    expect(d.sales).toBe(3000) // seller price: 1000 + 2000
    expect(d.paid).toBe(2700) // what buyers paid: 900 + 1800
    expect(d.logistics).toBe(500) // 200 + 300
    expect(d.payout_net).toBe(1200) // 600 + 600
    expect(d.logistics_pct).toBeCloseTo((500 / 3000) * 100)
    expect(d.excluded_count).toBe(0)
  })

  it('drops the excluded rows, exactly as the backend dashboard does', () => {
    const d = subsetDashboard([
      row({ revenue_seller_price: '1000' }),
      row({ nm_id: 2, revenue_seller_price: '9000', is_excluded: true }),
    ])

    expect(d.sales).toBe(1000) // the excluded 9000 is not counted
    expect(d.excluded_count).toBe(1)
  })

  it('treats a null cost as absent, not zero-in-the-denominator', () => {
    const d = subsetDashboard([row({ cogs: null, cost_price: null, sold_units: 5 })])

    expect(d.cogs).toBe(0)
    expect(d.uncosted_count).toBe(1)
  })

  it('carries «Прочие удержания» from the backend dashboard, not per-SKU ads', () => {
    // Ad invoices/subscriptions/transit are account-level with no SKU, so a
    // filtered subtotal keeps the whole-account figure and flags itself filtered.
    const base = { other_deductions: '436765', advertising: '329594' }
    const d = subsetDashboard(
      [row({ advertising: '50' }), row({ nm_id: 2, advertising: '70' })],
      base,
    )

    expect(d.other_deductions).toBe(436765) // account-level, NOT 50 + 70
    expect(d.advertising).toBe(329594)
    expect(d.filtered).toBe(true)
  })
})

describe('sumRows — строка «Итого»', () => {
  /** A flat table row, the shape `toRow` produces. */
  function flat(overrides = {}) {
    return {
      nmId: 1,
      saName: 'M-A',
      isBucket: false,
      isExcluded: false,
      orders: 100,
      sold: 40,
      returned: 4,
      sales: 1000,
      paid: 900,
      logistics: 200,
      penalties: 10,
      cogs: 300,
      advertising: 90,
      adBonus: 20,
      advertisingCash: 70,
      payout: 600,
      profit: 230,
      ...overrides,
    }
  }

  it('складывает суммы и пересчитывает доли от сложенных баз', () => {
    const t = sumRows([flat(), flat({ nmId: 2, sales: 3000, paid: 2700, logistics: 300 })])

    expect(t.sales).toBe(4000)
    expect(t.logistics).toBe(500)
    expect(t.sold).toBe(80)
    // Доля суммы, а не среднее долей: 500 / (900 + 2700).
    expect(t.logisticsPct).toBeCloseTo((500 / 3600) * 100)
    expect(t.returnPct).toBeCloseTo((8 / 80) * 100)
  })

  it('не берёт в сумму строки, отмеченные «Не включать в общий счёт»', () => {
    const t = sumRows([flat(), flat({ nmId: 2, sales: 9000, isExcluded: true })])

    expect(t.sales).toBe(1000)
    expect(t.excludedCount).toBe(1)
  })

  it('возвращает счета за рекламу обратно, когда в сумме есть строка счёта', () => {
    // Счёт «WB Продвижение» уже удержан внутри «К перечислению» строки счёта,
    // поэтому вычесть сверху ещё и открут — значит списать рекламу дважды.
    const bucket = flat({
      nmId: 0,
      isBucket: true,
      orders: null,
      sold: 0,
      returned: 0,
      sales: 0,
      paid: 0,
      logistics: 0,
      penalties: 0,
      cogs: null,
      advertising: null,
      adBonus: null,
      advertisingCash: null,
      payout: -500,
      profit: null,
    })
    const t = sumRows([flat(), bucket], 500)

    // 600 - 500 (удержанный счёт) + 500 (он же, возвращённый) - 300 - 70
    expect(t.profit).toBe(230)
  })

  it('без строки счёта поправки нет — удержания счёта в сумме тоже нет', () => {
    const t = sumRows([flat()], 500)

    expect(t.profit).toBe(600 - 300 - 70)
  })

  it('не выдаёт ноль за «не знаем»: колонка без данных остаётся пустой', () => {
    const t = sumRows([flat({ orders: null, advertising: null, advertisingCash: null })])

    expect(t.orders).toBeNull()
    expect(t.advertising).toBeNull()
    expect(t.advertisingPct).toBeNull()
  })

  it('на пустой таблице итога нет', () => {
    expect(sumRows([])).toBeNull()
    expect(sumRows([flat({ isExcluded: true })])).toBeNull()
  })
})
