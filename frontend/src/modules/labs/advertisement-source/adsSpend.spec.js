import { spendWindow, zoneBars, zoneShares } from '@/modules/labs/advertisement-source/adsSpend'

describe('spendWindow', () => {
  it('splits the window by funding source and bid type, largest kind first', () => {
    // The cards say «ваши деньги» and «деньги WB» — a bonus row landing on
    // the balance side would overstate what the seller paid.
    const ads = {
      daily_kind: [
        ['2026-08-01', 'Единая Ставка', 'balance', 100],
        ['2026-08-01', 'Ручная Ставка', 'balance', 300],
        ['2026-08-02', 'Ручная Ставка', 'promo', 50],
      ],
    }

    const window = spendWindow(ads, '2026-08-01', '2026-08-02')

    expect(window).toMatchObject({ total: 450, balance: 400, promo: 50 })
    expect(window.kinds.map((k) => [k.name, k.total, k.promo])).toEqual([
      ['Ручная Ставка', 350, 50],
      ['Единая Ставка', 100, 0],
    ])
  })

  it('counts only the days inside the window, both ends inclusive', () => {
    const ads = {
      daily_kind: [
        ['2026-07-31', 'Ручная Ставка', 'balance', 1000],
        ['2026-08-01', 'Ручная Ставка', 'balance', 10],
        ['2026-08-07', 'Ручная Ставка', 'balance', 20],
        ['2026-08-08', 'Ручная Ставка', 'balance', 1000],
      ],
    }

    const window = spendWindow(ads, '2026-08-01', '2026-08-07')

    expect(window.total).toBe(30)
  })

  it('keeps spend with no bid type in its own row instead of dropping it', () => {
    const ads = { daily_kind: [['2026-08-01', '', 'balance', 70]] }

    const window = spendWindow(ads, '2026-08-01', '2026-08-01')

    expect(window.kinds).toEqual([{ name: 'Без типа', total: 70, balance: 70, promo: 0 }])
  })
})

describe('zoneShares', () => {
  it('measures the search share per bid type from campaign statistics', () => {
    const ads = {
      zones_daily: [
        ['2026-08-01', 'manual', 90, 10],
        ['2026-08-01', 'unified', 20, 80],
      ],
    }

    const zones = zoneShares(ads, '2026-08-01', '2026-08-01')

    expect(zones.share).toBeCloseTo(110 / 200)
    expect(zones.byKind['Ручная Ставка'].share).toBeCloseTo(0.9)
    expect(zones.byKind['Единая Ставка'].share).toBeCloseTo(0.2)
  })

  it('counts a row with an unknown bid toward the overall share only', () => {
    // It is real spend, so dropping it would skew «Вся реклама»; it just cannot
    // be put on a bid-type row.
    const ads = {
      zones_daily: [
        ['2026-08-01', 'manual', 50, 50],
        ['2026-08-01', '', 0, 100],
      ],
    }

    const zones = zoneShares(ads, '2026-08-01', '2026-08-01')

    expect(zones.share).toBeCloseTo(0.25)
    expect(Object.keys(zones.byKind)).toEqual(['Ручная Ставка'])
  })

  it('has no share, rather than a zero one, for a window the statistics miss', () => {
    const ads = { zones_daily: [['2026-01-01', 'manual', 5, 5]] }

    const zones = zoneShares(ads, '2026-08-01', '2026-08-31')

    expect(zones).toEqual({ share: null, days: 0, byKind: {} })
  })
})

describe('zoneBars', () => {
  it("applies the statistics' share to the history's money, not its own sums", () => {
    // History and statistics disagree by ~1 %; the bars must add up to the
    // «Потрачено» card, not to the statistics' total.
    const window = { total: 1000, kinds: [{ name: 'Ручная Ставка', total: 1000 }] }
    const zones = { share: 0.6, byKind: { 'Ручная Ставка': { share: 0.6 } } }

    const bars = zoneBars(window, zones)

    expect(bars[0]).toEqual({ label: 'Вся реклама', search: 600, rest: 400 })
  })
})
