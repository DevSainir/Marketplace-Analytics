/**
 * The balance grid's view logic: order, filtering, and what the panels show.
 *
 * The panels are the part that can silently lie, and they are computed here
 * rather than fetched because a mark applies without a round trip. Three rules
 * carry the weight: a «Не считать» warehouse leaves every total but keeps its
 * own column figures, a filter re-totals to the rows on screen (a bottom row
 * still summing the whole catalogue is a number a seller would act on), and an
 * uncosted SKU never contributes a zero in place of an unknown. A fourth joins
 * them: goods in transit are money the seller has already spent, so they belong
 * in «По себестоимости» — but never in «По остаткам», which is what can ship.
 */
import { describe, expect, it } from 'vitest'
import { ref } from 'vue'

import { currencySuffix, useBalanceRows } from '@/modules/finreports/useBalanceRows'

const BRUKI = {
  nm_id: 953770957,
  sa_name: 'm-trx01-blk',
  subject_name: 'Брюки',
  brand_name: 'NORTH LINE',
  cost_price: '800',
  cells: [
    // Five units riding to or from a buyer, worth 4 000 on top of the 57 600
    // lying in Тула — the whole point of the «В пути» column.
    { warehouse_name: 'Тула', quantity: 72, in_way: 5, balance: '57600', in_way_balance: '4000' },
    { warehouse_name: 'Коледино', quantity: 8, in_way: 0, balance: '6400', in_way_balance: '0' },
    { warehouse_name: 'СЦ Брак', quantity: 5, in_way: 0, balance: '4000', in_way_balance: '0' },
  ],
}

const SHORTS = {
  nm_id: 611450917,
  sa_name: 'm-wdx02-wht',
  subject_name: 'Шорты',
  brand_name: 'OTHER',
  cost_price: null,
  cells: [{ warehouse_name: 'Тула', quantity: 40, in_way: 0, balance: null, in_way_balance: null }],
}

function payload(overrides = {}) {
  return ref({
    stat_date: '2026-08-03',
    currency: 'KGS',
    rows: [BRUKI, SHORTS],
    uncounted_warehouses: [],
    uncosted_count: 1,
    notes: [],
    ...overrides,
  })
}

describe('useBalanceRows', () => {
  it('totals the visible rows across the counted warehouses', () => {
    const { totals } = useBalanceRows(payload())

    expect(totals.value.quantity).toBe(125)
    expect(totals.value.inWay).toBe(5)
    // 68 000 lying in the warehouses plus the 4 000 riding between them.
    expect(totals.value.balance).toBe(72000)
  })

  it('leaves a «Не считать» warehouse out of the totals but keeps its column', () => {
    const { columns, tableRows, totals } = useBalanceRows(
      payload({ uncounted_warehouses: ['СЦ Брак'] }),
    )

    const brak = columns.value.find((c) => c.name === 'СЦ Брак')
    expect(brak.isUncounted).toBe(true)
    // Last column, still carrying its own figures…
    expect(columns.value.at(-1).name).toBe('СЦ Брак')
    expect(totals.value.warehouses.at(-1).balance).toBe(4000)
    // …and out of both the row total and the corner.
    expect(tableRows.value.find((r) => r.nmId === BRUKI.nm_id).totalBalance).toBe(68000)
    expect(totals.value.balance).toBe(68000)
    expect(totals.value.quantity).toBe(120)
  })

  it('leaves a «Не считать» SKU out of every total but keeps its own row', () => {
    const { tableRows, totals, isRowBoundary } = useBalanceRows(
      payload({ uncounted_skus: [BRUKI.nm_id] }),
    )

    const excluded = tableRows.value.find((r) => r.nmId === BRUKI.nm_id)

    // Its own «Итого по артикулу» still stands — the seller wants to see what
    // is lying there; it just is not theirs to count.
    expect(excluded.isUncounted).toBe(true)
    expect(excluded.totalQuantity).toBe(85)
    expect(excluded.totalInWay).toBe(5)
    expect(excluded.totalBalance).toBe(72000)
    // …and it reaches neither the column totals nor the corner. All that is
    // left in the count is the uncosted SKU, which carries units and no money.
    expect(totals.value.quantity).toBe(40)
    expect(totals.value.inWay).toBe(0)
    expect(totals.value.balance).toBe(0)
    expect(totals.value.warehouses.find((w) => w.name === 'Коледино').quantity).toBe(0)
    expect(totals.value.warehouses.find((w) => w.name === 'Тула').quantity).toBe(40)
    // Excluded rows sink to the bottom, behind a seam of their own.
    expect(tableRows.value.at(-1).nmId).toBe(BRUKI.nm_id)
    expect(isRowBoundary(1)).toBe(true)
  })

  it('re-totals the panels over the visible rows once a filter is on', () => {
    const { brandFilter, tableRows, totals } = useBalanceRows(payload())

    brandFilter.value = 'NORTH LINE'

    expect(tableRows.value).toHaveLength(1)
    expect(totals.value.quantity).toBe(85)
    expect(totals.value.balance).toBe(72000)
    // The emptied column stays in place — a column disappearing mid-search
    // makes the grid jump under the reader.
    expect(totals.value.warehouses.map((w) => w.name)).toEqual(['Тула', 'Коледино', 'СЦ Брак'])
  })

  it('keeps an uncosted SKU out of the money but not out of the units', () => {
    const { tableRows, totals } = useBalanceRows(payload())

    const uncosted = tableRows.value.find((r) => r.nmId === SHORTS.nm_id)

    expect(uncosted.totalQuantity).toBe(40)
    expect(uncosted.totalBalance).toBeNull()
    expect(totals.value.quantity).toBe(125)
  })

  it('keeps goods in transit out of the units but inside the money', () => {
    const { tableRows, totals } = useBalanceRows(payload())

    const bruki = tableRows.value.find((r) => r.nmId === BRUKI.nm_id)

    // «По остаткам» is what can be shipped today — the five in transit are not
    // part of it, and a seller reading 85 must not be reading 90.
    expect(bruki.totalQuantity).toBe(85)
    expect(bruki.totalInWay).toBe(5)
    // «По себестоимости» is money already spent, which the five very much are.
    expect(bruki.totalBalance).toBe(72000)
    // A cell is the SHELF and nothing else — units and money alike. The goods
    // in transit sit on no shelf and are reported once, in the row's summary.
    expect(bruki.byWarehouse['Тула']).toEqual({ quantity: 72, balance: 57600 })
    // So «Итого по складу» sums the shelves and the corner sums the holding.
    // They are MEANT to disagree, by exactly the money that is in transit —
    // the day they tie out is the day «В пути» stopped being counted.
    const shelves = totals.value.warehouses.reduce((sum, w) => sum + w.balance, 0)
    expect(shelves).toBe(68000)
    expect(totals.value.balance - shelves).toBe(4000)
  })

  it('sinks «не считается» rows and columns to the back without a refetch', () => {
    const balance = payload()
    const { columns, tableRows, uncountedCount, isGroupBoundary } = useBalanceRows(balance)

    // What the store does optimistically when the seller clicks «Не считать».
    balance.value.uncounted_skus = [SHORTS.nm_id]
    balance.value.uncounted_warehouses = ['Коледино']

    expect(tableRows.value.at(-1).nmId).toBe(SHORTS.nm_id)
    expect(columns.value.at(-1).name).toBe('Коледино')
    expect(uncountedCount.value).toBe(1)
    expect(isGroupBoundary(columns.value.length - 1)).toBe(true)
    expect(isGroupBoundary(0)).toBe(false)
  })

  it('searches the article, nm, subject and brand of a row', () => {
    const { query, tableRows } = useBalanceRows(payload())

    query.value = '611450917'

    // The row is found by its lowercase article but rendered uppercase.
    expect(tableRows.value.map((r) => r.saName)).toEqual(['M-WDX02-WHT'])
  })
})

describe('currencySuffix', () => {
  it('shortens the settlement currency to one character', () => {
    // A three-letter code per cell would cost a whole warehouse of screen width.
    expect(currencySuffix('KGS')).toBe('с')
    expect(currencySuffix('RUB')).toBe('₽')
    expect(currencySuffix('')).toBe('')
  })
})
