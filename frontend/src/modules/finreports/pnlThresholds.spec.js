import { tone } from '@/modules/finreports/pnlThresholds'

describe('рамки подсветки и база цены', () => {
  it('одна и та же доля логистики красная по цене селлера и обычная по цене реализации', () => {
    // Over a smaller revenue (after SPP) the same logistics is a larger
    // percentage, and the seller's-price bounds would tint extra rows on this base.
    expect(tone('logisticsPct', 40, 'seller')).toBe('negative')
    expect(tone('logisticsPct', 40, 'paid')).toBe('')
  })

  it('метрики, которые не делятся на выручку, от базы не зависят', () => {
    expect(tone('roi', 250, 'paid')).toBe(tone('roi', 250, 'seller'))
    expect(tone('returnPct', 25, 'paid')).toBe('negative')
  })

  it('ROI красный только ниже 30 %: выше нуля партия уже окупилась', () => {
    expect(tone('roi', 29)).toBe('negative')
    expect(tone('roi', 80)).toBe('')
    expect(tone('roi', 200)).toBe('positive')
  })

  it('у выкупа размера свои рамки — это другая мера, чем выкуп WB', () => {
    expect(tone('buyoutPct', 32)).toBe('positive')
    expect(tone('sizeBuyoutPct', 32)).toBe('')
  })

  it('ДРР до 20 % нейтральный при любой базе, выше — красный, зелёного нет', () => {
    for (const base of ['seller', 'paid']) {
      expect(tone('advertisingPct', 1, base)).toBe('')
      expect(tone('advertisingPct', 20, base)).toBe('')
      expect(tone('advertisingPct', 20.5, base)).toBe('negative')
    }
  })
})
