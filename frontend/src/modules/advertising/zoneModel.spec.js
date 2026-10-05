import { bidCards } from '@/modules/advertising/zoneModel'

const ZONES = [
  { zone: 'cpm_manual_search', spend: '600', bonus: '60' },
  { zone: 'cpm_manual_catalog', spend: '100', bonus: '0' },
  { zone: 'cpm_unified_search', spend: '50', bonus: '0' },
  { zone: 'cpm_unified_shelves', spend: '250', bonus: '20' },
]

describe('bidCards', () => {
  it('keeps one card per campaign kind in a fixed order, idle ones at zero', () => {
    // The order is WB's billing, not size: a card must not move between
    // periods, and a kind that did not run stays on the row.
    const { cards } = bidCards(ZONES)

    expect(cards.map((c) => [c.label, c.spend])).toEqual([
      ['Ручной поиск', 700],
      ['Ручные полки', 0],
      ['Единая ставка', 300],
      ['CPC', 0],
    ])
  })

  it('splits a card by zone as a share of the card, and the card as a share of everything', () => {
    const manual = bidCards(ZONES).cards[0]

    expect(manual.share).toBeCloseTo(0.7)
    expect(manual.bonus).toBe(60)
    expect(manual.zones.map((z) => [z.label, z.spend])).toEqual([
      ['Поиск', 600],
      ['Каталог', 100],
    ])
    expect(manual.zones[1].share).toBeCloseTo(100 / 700)
  })

  it('gives единая ставка no catalogue', () => {
    // WB reports only its search slice; the rest is the shelves.
    const unified = bidCards(ZONES).cards.find((c) => c.key === 'unified')

    expect(unified.zones.map((z) => z.label)).toEqual(['Поиск', 'Полки'])
  })

  it('keeps spend with no campaign settings off the cards, but counts it in the shares', () => {
    const { cards, untyped } = bidCards([
      { zone: 'cpc_shelves', spend: '75', bonus: '0' },
      { zone: 'unclassified', spend: '25', bonus: '0' },
    ])

    expect(untyped).toBe(25)
    expect(cards.find((c) => c.key === 'cpc').share).toBeCloseTo(0.75)
  })
})
