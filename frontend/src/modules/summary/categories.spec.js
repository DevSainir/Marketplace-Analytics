/**
 * Folding the per-article rows into "Revenue by category".
 *
 * This moved to the browser on purpose: grouping, sorting and the price base
 * used to be query parameters, and each click re-aggregated the whole
 * settlement window on the server. What is pinned here is the arithmetic that
 * came with it.
 */
import { UNNAMED } from '@/modules/heatmap'

import { buildCategories, revenueOf } from './categories'

const row = (over = {}) => ({
  nm_id: 1,
  code: 'm-trx01-blk',
  subject: 'Trousers',
  brand: 'NORTH LINE',
  revenue_paid: '600',
  revenue_seller: '1200',
  margin: '300',
  sold_units: 10,
  ...over,
})

describe('revenueOf', () => {
  it('reads the base the caller asked for', () => {
    expect(revenueOf(row(), 'paid')).toBe(600)
    expect(revenueOf(row(), 'seller')).toBe(1200)
  })
})

describe('buildCategories', () => {
  it('folds articles into their subject and counts them', () => {
    const bars = buildCategories(
      [
        row({ nm_id: 1, revenue_paid: '600', margin: '300', subject: 'Trousers' }),
        row({ nm_id: 2, revenue_paid: '400', margin: '100', subject: 'Trousers' }),
        row({ nm_id: 3, revenue_paid: '200', margin: '50', subject: 'Suits' }),
      ],
      { cut: 'subject', base: 'paid', sort: 'revenue' },
    )

    expect(bars[0].label).toBe('Trousers')
    expect(bars[0].revenue).toBe(1000)
    expect(bars[0].skuCount).toBe(2)
    expect(bars[1].skuCount).toBe(1)
  })

  it('withholds a group margin as soon as one of its articles has none', () => {
    // Letting the costed half stand would rank a brand above fully-costed ones
    // for being less well documented.
    const bars = buildCategories(
      [
        row({ nm_id: 1, brand: 'Complete', margin: '300' }),
        row({ nm_id: 2, brand: 'Incomplete', margin: null }),
      ],
      { cut: 'brand', base: 'paid', sort: 'revenue' },
    )

    const byLabel = Object.fromEntries(bars.map((bar) => [bar.label, bar]))
    expect(byLabel['Complete'].margin).toBe(300)
    expect(byLabel['Incomplete'].margin).toBeNull()
    expect(byLabel['Incomplete'].marginShare).toBeNull()
  })

  it('ranks by the chosen metric and keeps loss-makers visible', () => {
    // Sorting by margin must put a negative bar last, not drop it: that is the
    // row a seller most needs to see.
    const bars = buildCategories(
      [
        row({ nm_id: 1, revenue_paid: '100', margin: '90' }),
        row({ nm_id: 2, revenue_paid: '900', margin: '-50' }),
      ],
      { cut: 'sku', base: 'paid', sort: 'margin' },
    )

    expect(bars.map((bar) => bar.nm_id ?? bar.key)).toEqual(['1', '2'])
    expect(bars[1].margin).toBe(-50)
  })

  it('switches the whole block to the seller price without regrouping', () => {
    const rows = [row({ nm_id: 1, revenue_paid: '600', revenue_seller: '1200' })]

    const paid = buildCategories(rows, { cut: 'sku', base: 'paid', sort: 'revenue' })
    const seller = buildCategories(rows, { cut: 'sku', base: 'seller', sort: 'revenue' })

    expect(paid[0].revenue).toBe(600)
    expect(seller[0].revenue).toBe(1200)
  })

  it('shares add up to a hundred, because the block is its own total', () => {
    // Account-level money has no article and is not in these rows, so it is not
    // in the denominator either — the column a reader checks must close.
    const bars = buildCategories(
      [row({ nm_id: 1, revenue_paid: '600' }), row({ nm_id: 2, revenue_paid: '400' })],
      { cut: 'sku', base: 'paid', sort: 'revenue' },
    )

    expect(bars.reduce((sum, bar) => sum + bar.revenueShare, 0)).toBeCloseTo(100, 6)
  })

  it('labels an article WB never gave a subject rather than showing a blank', () => {
    const bars = buildCategories([row({ subject: '' })], {
      cut: 'subject',
      base: 'paid',
      sort: 'revenue',
    })

    expect(bars[0].label).toBe(UNNAMED)
  })

  it('is empty rather than broken when the window settled nothing', () => {
    expect(buildCategories([], { cut: 'sku', base: 'paid', sort: 'revenue' })).toEqual([])
  })
})

describe('buildCategories by "Groups"', () => {
  it('sums each group, and shares each against the articles, not the overlapping bars', () => {
    const rows = [
      row({ nm_id: 1, revenue_seller: '100', margin: '10' }),
      row({ nm_id: 2, revenue_seller: '300', margin: '30' }),
    ]
    const groups = [
      { id: 'a', name: 'Summer', nm_ids: [1, 2] },
      { id: 'b', name: 'Bestsellers', nm_ids: [2] },
    ]

    const bars = buildCategories(rows, { cut: 'group', base: 'seller', sort: 'revenue', groups })

    expect(bars.map((b) => [b.label, b.revenue, b.revenueShare])).toEqual([
      ['Summer', 400, 100],
      ['Bestsellers', 300, 75],
    ])
  })
})
