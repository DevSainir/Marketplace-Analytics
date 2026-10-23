/**
 * The balance grid's view logic: order, filtering, and what the panels show.
 *
 * The panels are the part that can silently lie, and they are computed here
 * rather than fetched because a mark applies without a round trip. Three rules
 * carry the weight: a "Don't count" warehouse leaves every total but keeps its
 * own column figures, a filter re-totals to the rows on screen (a bottom row
 * still summing the whole catalog is a number a seller would act on), and an
 * uncosted SKU never contributes a zero in place of an unknown. A fourth joins
 * them: goods in transit are money the seller has already spent, so they belong
 * in "At cost price" — but never in "In stock", which is what can ship.
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { ref } from 'vue'

import {
  groupBalanceRows,
  moneyFormatter,
  toRow,
  useBalanceRows,
} from '@/modules/finreports/useBalanceRows'

beforeEach(() => setActivePinia(createPinia()))

const TROUSERS = {
  nm_id: 953770957,
  sa_name: 'm-trx01-blk',
  subject_name: 'Trousers',
  brand_name: 'NORTH LINE',
  cost_price: '800',
  cells: [
    // Five units riding to or from a buyer, worth 4 000 on top of the 57 600
    // lying in Tula — the whole point of the "In transit" column.
    { warehouse_name: 'Tula', quantity: 72, in_way: 5, balance: '57600', in_way_balance: '4000' },
    { warehouse_name: 'Koledino', quantity: 8, in_way: 0, balance: '6400', in_way_balance: '0' },
    {
      warehouse_name: 'SC Defective',
      quantity: 5,
      in_way: 0,
      balance: '4000',
      in_way_balance: '0',
    },
  ],
}

const SHORTS = {
  nm_id: 611450917,
  sa_name: 'm-wdx02-wht',
  subject_name: 'Shorts',
  brand_name: 'OTHER',
  cost_price: null,
  cells: [{ warehouse_name: 'Tula', quantity: 40, in_way: 0, balance: null, in_way_balance: null }],
}

function payload(overrides = {}) {
  return ref({
    stat_date: '2026-08-03',
    currency: 'KGS',
    rows: [TROUSERS, SHORTS],
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

  it('leaves a "Don\'t count" warehouse out of the totals but keeps its column', () => {
    const { columns, tableRows, totals } = useBalanceRows(
      payload({ uncounted_warehouses: ['SC Defective'] }),
    )

    const defective = columns.value.find((c) => c.name === 'SC Defective')
    expect(defective.isUncounted).toBe(true)
    // Last column, still carrying its own figures…
    expect(columns.value.at(-1).name).toBe('SC Defective')
    expect(totals.value.warehouses.at(-1).balance).toBe(4000)
    // …and out of both the row total and the corner.
    expect(tableRows.value.find((r) => r.nmId === TROUSERS.nm_id).totalBalance).toBe(68000)
    expect(totals.value.balance).toBe(68000)
    expect(totals.value.quantity).toBe(120)
  })

  it('leaves a "Don\'t count" SKU out of every total but keeps its own row', () => {
    const { tableRows, totals, isRowBoundary } = useBalanceRows(
      payload({ uncounted_skus: [TROUSERS.nm_id] }),
    )

    const excluded = tableRows.value.find((r) => r.nmId === TROUSERS.nm_id)

    // Its own "SKU total" still stands — the seller wants to see what
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
    expect(totals.value.warehouses.find((w) => w.name === 'Koledino').quantity).toBe(0)
    expect(totals.value.warehouses.find((w) => w.name === 'Tula').quantity).toBe(40)
    // Excluded rows sink to the bottom, behind a seam of their own.
    expect(tableRows.value.at(-1).nmId).toBe(TROUSERS.nm_id)
    expect(isRowBoundary(1)).toBe(true)
  })

  it('re-totals the panels over the visible rows once a filter is on', () => {
    const { brandFilter, tableRows, totals } = useBalanceRows(payload())

    brandFilter.value = ['NORTH LINE']

    expect(tableRows.value).toHaveLength(1)
    expect(totals.value.quantity).toBe(85)
    expect(totals.value.balance).toBe(72000)
    // The emptied column stays in place — a column disappearing mid-search
    // makes the grid jump under the reader.
    expect(totals.value.warehouses.map((w) => w.name)).toEqual(['Tula', 'Koledino', 'SC Defective'])
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

    const trousers = tableRows.value.find((r) => r.nmId === TROUSERS.nm_id)

    // "In stock" is what can be shipped today — the five in transit are not
    // part of it, and a seller reading 85 must not be reading 90.
    expect(trousers.totalQuantity).toBe(85)
    expect(trousers.totalInWay).toBe(5)
    // "At cost price" is money already spent, which the five very much are.
    expect(trousers.totalBalance).toBe(72000)
    // A cell is the SHELF and nothing else — units and money alike. The goods
    // in transit sit on no shelf and are reported once, in the row's summary.
    expect(trousers.byWarehouse['Tula']).toEqual({ quantity: 72, balance: 57600 })
    // So "Warehouse total" sums the shelves and the corner sums the holding.
    // They are MEANT to disagree, by exactly the money that is in transit —
    // the day they tie out is the day "In transit" stopped being counted.
    const shelves = totals.value.warehouses.reduce((sum, w) => sum + w.balance, 0)
    expect(shelves).toBe(68000)
    expect(totals.value.balance - shelves).toBe(4000)
  })

  it('sinks "not counted" rows and columns to the back without a refetch', () => {
    const balance = payload()
    const { columns, tableRows, uncountedCount, isGroupBoundary } = useBalanceRows(balance)

    // What the store does optimistically when the seller clicks "Don't count".
    balance.value.uncounted_skus = [SHORTS.nm_id]
    balance.value.uncounted_warehouses = ['Koledino']

    expect(tableRows.value.at(-1).nmId).toBe(SHORTS.nm_id)
    expect(columns.value.at(-1).name).toBe('Koledino')
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

describe('moneyFormatter', () => {
  const plain = (text) => text.replace(/\s/g, ' ')

  it('signs the balance with its currency, one character for the som', () => {
    // A three-letter code per cell would cost a whole warehouse of screen width.
    expect(plain(moneyFormatter('KGS')(57600))).toBe('KGS 57,600')
  })

  it('prints no sign when the currency is unknown, and a dash for a missing figure', () => {
    expect(plain(moneyFormatter('')(57600))).toBe('57,600')
    expect(moneyFormatter('KGS')(null)).toBe('—')
  })
})

describe('groupBalanceRows', () => {
  const flat = (r, uncountedSkus = new Set()) => toRow(r, new Set(), uncountedSkus)

  it('sums a subject warehouse by warehouse, money unknown only when no article has a cost', () => {
    const rows = [flat(TROUSERS), flat({ ...SHORTS, subject_name: 'Trousers' })]

    const [trousers] = groupBalanceRows(rows, 'subject', [])

    // A one-word label is a name, not a code: it is not shouted in capitals.
    expect(trousers).toMatchObject({ saName: 'Trousers', n: 2, isGroup: true })
    expect(trousers.byWarehouse['Tula']).toEqual({ quantity: 112, balance: 57600 })
    expect(trousers.totalQuantity).toBe(125)
    expect(trousers.totalBalance).toBe(72000)
    expect(groupBalanceRows([flat(SHORTS)], 'subject', [])[0].totalBalance).toBeNull()
  })

  it('leaves a "Don\'t count" article out of its group', () => {
    const rows = [flat(TROUSERS, new Set([TROUSERS.nm_id])), flat(SHORTS)]

    const out = groupBalanceRows(rows, 'brand', [])

    expect(out.map((r) => r.saName)).toEqual(['OTHER'])
  })
})
