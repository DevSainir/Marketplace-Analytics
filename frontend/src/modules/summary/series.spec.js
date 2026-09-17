/**
 * The chart lines, and the one rule that matters in them: when is a point
 * missing rather than zero.
 *
 * ДРР is a division, so it has two ways of being unknown — no advertising
 * statistics for the day, and no price to value that day's orders at. Both used
 * to be expressible as zero, and both read as a claim: free advertising in one
 * direction, infinite spend in the other.
 */
import { describe, expect, it } from 'vitest'

import { drr, orderSeries, revenueSeries, saleSeries } from '@/modules/summary/series'

const day = (over = {}) => ({
  day: '2026-09-10',
  revenue_paid: '1000',
  revenue_seller: '1200',
  margin: '300',
  orders: 40,
  orders_amount: '2000',
  sold_units: 12,
  ad_spend: '100',
  ...over,
})

describe('drr', () => {
  it('is the share of what the advertising sold', () => {
    expect(drr('100', '2000')).toBe(5)
  })

  it('is unknown without advertising statistics', () => {
    expect(drr(null, '2000')).toBeNull()
  })

  it('is unknown when the orders have no price to be valued at', () => {
    expect(drr('100', null)).toBeNull()
  })

  it('is unknown rather than infinite on a day that sold nothing', () => {
    expect(drr('100', '0')).toBeNull()
  })
})

describe('the day charts', () => {
  it('puts ДРР on its own axis, as a percentage', () => {
    const [count, share] = orderSeries([day()])

    expect(count.axis).toBeUndefined()
    expect(share.axis).toBe('right')
    expect(share.percent).toBe(true)
  })

  it('reads sales against the price base the reader picked', () => {
    const [, paid] = saleSeries([day()], { base: 'paid' })
    const [, seller] = saleSeries([day()], { base: 'seller' })

    expect(paid.values[0]).toBe(10)
    expect(seller.values[0]).toBeCloseTo(8.333, 3)
  })

  it('draws a day WB has not calculated without inventing a zero', () => {
    const pending = day({ revenue_paid: null, revenue_seller: null, sold_units: null })
    const [units, share] = saleSeries([pending], { base: 'seller' })

    expect(units.values[0]).toBeNull()
    expect(share.values[0]).toBeNull()
  })
})

describe('the revenue chart', () => {
  it('omits the margin line entirely while the window is uncosted', () => {
    const lines = revenueSeries([day()], { base: 'seller', costed: false })

    expect(lines.map((line) => line.name)).toEqual(['Выручка'])
  })
})
