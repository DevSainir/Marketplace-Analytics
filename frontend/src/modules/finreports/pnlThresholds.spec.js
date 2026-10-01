import { tone } from '@/modules/finreports/pnlThresholds'

describe('рамки подсветки и база цены', () => {
  it('одна и та же доля логистики красная по цене селлера и обычная по цене реализации', () => {
    // От меньшей выручки (после СПП) та же логистика даёт больший процент, и
    // рамки цены селлера красили бы на этой базе лишние строки.
    expect(tone('logisticsPct', 40, 'seller')).toBe('negative')
    expect(tone('logisticsPct', 40, 'paid')).toBe('')
  })

  it('метрики, которые не делятся на выручку, от базы не зависят', () => {
    expect(tone('roi', 250, 'paid')).toBe(tone('roi', 250, 'seller'))
    expect(tone('returnPct', 25, 'paid')).toBe('negative')
  })

  it('у выкупа размера свои рамки — это другая мера, чем выкуп WB', () => {
    expect(tone('buyoutPct', 32)).toBe('positive')
    expect(tone('sizeBuyoutPct', 32)).toBe('')
  })
})
