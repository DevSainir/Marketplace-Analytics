import { sizeAtBase } from '@/modules/finreports/priceBase'
import { groupPnlRows, subsetDashboard, sumRows, toRow } from '@/modules/finreports/usePnlSkuRows'

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
      buyoutUnits: 30,
      decidedUnits: 40,
      sales: 1000,
      seller: 1000,
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
    // The share of the sum, not the average of shares, and of «Продажи» (the
    // seller's price before SPP), like the card above: 500 / (1000 + 3000). Until
    // 26.09.2026 «Итого» divided by «Оплачено», and one page showed two
    // logistics shares.
    expect(t.logisticsPct).toBeCloseTo((500 / 4000) * 100)
    expect(t.returnPct).toBeCloseTo((8 / 80) * 100)
  })

  it('выкуп итога — выкупы к решённым заказам по сумме штук, а не среднее процентов', () => {
    // 30/40 and 10/100: the average of percentages would give 42.5 %; by units it is 40/140.
    const t = sumRows([flat(), flat({ nmId: 2, buyoutUnits: 10, decidedUnits: 100 })])

    expect(t.decidedUnits).toBe(140)
    expect(t.buyoutPct).toBeCloseTo((40 / 140) * 100)
  })

  it('без воронки выкуп итога неизвестен, а не ноль', () => {
    const t = sumRows([flat({ buyoutUnits: null, decidedUnits: null })])

    expect(t.buyoutPct).toBeNull()
  })

  it('не берёт в сумму строки, отмеченные «Не включать в общий счёт»', () => {
    const t = sumRows([flat(), flat({ nmId: 2, sales: 9000, isExcluded: true })])

    expect(t.sales).toBe(1000)
    expect(t.excludedCount).toBe(1)
  })

  it('возвращает счета за рекламу обратно, когда в сумме есть строка счёта', () => {
    // The «WB Продвижение» invoice is already withheld inside the account row's
    // «К перечислению», so deducting the ad spend on top would charge
    // advertising twice.
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

    // 600 - 500 (withheld invoice) + 500 (the same, added back) - 300 - 70
    expect(t.profit).toBe(230)
  })

  it('без данных по рекламе счёт не возвращается — вычитать нечего', () => {
    // The invoice is then the only advertising figure, and it stays inside «К
    // перечислению». Adding it back with nothing deducted instead would show
    // profit higher by all the period's invoices. The backend does the same.
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
    const t = sumRows([flat({ advertising: null, advertisingCash: null }), bucket], 500)

    // 600 - 500 (withheld invoice) - 300, no ad spend and no invoice added back
    expect(t.profit).toBe(-200)
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

describe('база цены — «Цена селлера» или «Цена реализации»', () => {
  const backendRow = row({ advertising: '90', net_profit: '180', spp_pct: '10.00' })

  it('по цене селлера делит на выручку до СПП', () => {
    const r = toRow(backendRow, false, 'seller')

    expect(r.sales).toBe(1000)
    expect(r.logisticsPct).toBeCloseTo(20) // 200 / 1000
    expect(r.advertisingPct).toBeCloseTo(9) // 90 / 1000
    expect(r.profitPct).toBeCloseTo(18) // 180 / 1000
    expect(r.averageCheque).toBeCloseTo(1000 / 9) // 10 sold − 1 returned
  })

  it('по цене реализации делит то же самое на выручку после СПП', () => {
    const r = toRow(backendRow, false, 'paid')

    expect(r.sales).toBe(900)
    expect(r.logisticsPct).toBeCloseTo((200 / 900) * 100)
    expect(r.advertisingPct).toBeCloseTo(10)
    expect(r.profitPct).toBeCloseTo(20)
    expect(r.averageCheque).toBeCloseTo(100)
  })

  it('не двигает то, что на выручку не делится', () => {
    // The payout, profit in money and SPP are the same on either base.
    const seller = toRow(backendRow, false, 'seller')
    const paid = toRow(backendRow, false, 'paid')

    expect(paid.profit).toBe(seller.profit)
    expect(paid.payout).toBe(seller.payout)
    expect(paid.sppPct).toBe(seller.sppPct)
  })

  it('«Итого» по цене реализации: доли от суммы оплаченного, СПП — от суммы до СПП', () => {
    const t = sumRows([toRow(backendRow, false, 'paid'), toRow(backendRow, false, 'paid')])

    expect(t.sales).toBe(1800)
    expect(t.logisticsPct).toBeCloseTo((400 / 1800) * 100)
    expect(t.averageCheque).toBeCloseTo(100) // 1800 / 18 net units
    expect(t.sppPct).toBeCloseTo(10) // (2000 − 1800) / 2000
  })

  it('размер: цена × штуки остаётся выручкой при любой базе', () => {
    const size = {
      sold_units: 12,
      returned_units: 2,
      revenue_seller_price: '5000',
      revenue_paid: '4000',
      logistics_total: '1000',
    }

    expect(sizeAtBase(size, 'seller')).toEqual({ price: 500, revenue: 5000, logisticsPct: 20 })
    expect(sizeAtBase(size, 'paid')).toEqual({ price: 400, revenue: 4000, logisticsPct: 25 })
  })
})

describe('ДРР артикула, который вернули больше, чем продали', () => {
  it('не показывается вовсе, а не уходит в минус', () => {
    const r = toRow(row({ revenue_seller_price: '-200', revenue_paid: '-180' }), false, 'seller')

    expect(r.advertisingPct).toBeNull()
  })
})

describe('groupPnlRows', () => {
  const flat = (over) => toRow(row({ subject_name: 'Брюки', ...over }))

  it('sums the articles of a subject into one row, with no WB id or mark of its own', () => {
    const rows = [flat({ nm_id: 1 }), flat({ nm_id: 2 }), flat({ nm_id: 3, subject_name: 'Шорты' })]

    const [trousers, shorts] = groupPnlRows(rows, 'subject', [])

    expect(trousers).toMatchObject({ saName: 'Брюки', n: 2, isGroup: true, isSku: false })
    expect(trousers.sales).toBe(2000)
    expect(trousers.logisticsPct).toBe(20) // re-divided, not averaged
    expect(shorts).toMatchObject({ saName: 'Шорты', n: 1, sales: 1000 })
  })

  it('leaves the «Не включать» articles out of a sum, and a bucket of only those out entirely', () => {
    const rows = [
      flat({ nm_id: 1 }),
      flat({ nm_id: 2, is_excluded: true }),
      flat({ nm_id: 3, subject_name: 'Шорты', is_excluded: true }),
    ]

    const out = groupPnlRows(rows, 'subject', [])

    expect(out.map((r) => [r.saName, r.sales])).toEqual([['Брюки', 1000]])
  })

  it('counts an article in every group it is in', () => {
    const groups = [
      { id: 'a', name: 'Лето', nm_ids: [1, 2] },
      { id: 'b', name: 'Хиты', nm_ids: [2] },
    ]

    const out = groupPnlRows(
      [flat({ nm_id: 1 }), flat({ nm_id: 2 }), flat({ nm_id: 3 })],
      'group',
      groups,
    )

    expect(out.map((r) => [r.saName, r.n])).toEqual([
      ['Лето', 2],
      ['Хиты', 1],
      ['Без группы', 1],
    ])
  })
})
