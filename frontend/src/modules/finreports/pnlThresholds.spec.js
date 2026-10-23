import { tone } from '@/modules/finreports/pnlThresholds'

describe('highlight bounds and the price base', () => {
  it('paints the same logistics share red at seller price and plain at customer price', () => {
    // Over a smaller revenue (after the WB discount) the same logistics is a larger
    // percentage, and the seller's-price bounds would tint extra rows on this base.
    expect(tone('logisticsPct', 40, 'seller')).toBe('negative')
    expect(tone('logisticsPct', 40, 'paid')).toBe('')
  })

  it('leaves the metrics not divided by revenue independent of the base', () => {
    expect(tone('roi', 250, 'paid')).toBe(tone('roi', 250, 'seller'))
    expect(tone('returnPct', 25, 'paid')).toBe('negative')
  })

  it('paints ROI red only below 30%: above zero the batch has already paid off', () => {
    expect(tone('roi', 29)).toBe('negative')
    expect(tone('roi', 80)).toBe('')
    expect(tone('roi', 200)).toBe('positive')
  })

  it("gives the size buyout its own bounds — it is a different measure from WB's buyout", () => {
    expect(tone('buyoutPct', 32)).toBe('positive')
    expect(tone('sizeBuyoutPct', 32)).toBe('')
  })

  it('keeps ACoS up to 20% neutral at either base, red above, never green', () => {
    for (const base of ['seller', 'paid']) {
      expect(tone('advertisingPct', 1, base)).toBe('')
      expect(tone('advertisingPct', 20, base)).toBe('')
      expect(tone('advertisingPct', 20.5, base)).toBe('negative')
    }
  })
})
