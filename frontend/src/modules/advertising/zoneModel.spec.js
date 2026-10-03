import { zonePies, zoneRows } from '@/modules/advertising/zoneModel'

const ZONES = [
  { zone: 'cpm_manual_search', spend: '600', bonus: '60' },
  { zone: 'cpm_manual_catalog', spend: '100', bonus: '0' },
  { zone: 'cpm_unified_search', spend: '50', bonus: '0' },
  { zone: 'cpm_unified_shelves', spend: '250', bonus: '20' },
]

describe('zoneRows', () => {
  it('nests zones under their bid and payment type, groups summing their children', () => {
    // The table reads like indented code: CPM > ставка > кампания > зона.
    const rows = zoneRows(ZONES)

    expect(rows.map((r) => [r.depth, r.label, r.spend])).toEqual([
      [0, 'CPM', 1000],
      [1, 'Ручная ставка', 700],
      [2, 'Ручной поиск', 700],
      [3, 'Поиск', 600],
      [3, 'Каталог', 100],
      [2, 'Ручные полки', 0],
      [3, 'Полки', 0],
      [1, 'Единая ставка', 300],
      [2, 'Поиск', 50],
      [2, 'Полки', 250],
      [2, 'Каталог', 0],
      [0, 'CPC', 0],
      [1, 'Поиск', 0],
      [1, 'Полки', 0],
    ])
  })

  it('shows the unified catalogue as unknown, not as a zero', () => {
    // WB never splits it out of «Полки»; a 0 would claim it was measured.
    const catalog = zoneRows(ZONES).find((r) => r.id.endsWith('unified_catalog'))

    expect(catalog).toMatchObject({ unknown: true, share: null })
  })

  it('keeps every branch at zero, but shows «Без типа» only when something is untyped', () => {
    // A zero row says «эта ставка не крутилась»; «Без типа» is a gap in our
    // data, not a branch of WB's billing, so it has no business at zero.
    const quiet = zoneRows([{ zone: 'cpc_search', spend: '10', bonus: '0' }])
    const untyped = zoneRows([{ zone: 'unclassified', spend: '5', bonus: '0' }])

    expect(quiet.map((r) => r.label)).toContain('Ручные полки')
    expect(quiet.map((r) => r.label)).not.toContain('Без типа')
    expect(untyped.at(-1)).toMatchObject({ label: 'Без типа', spend: 5 })
  })
})

describe('zonePies', () => {
  it('splits every pie by zone, the whole pie summing them all, and keeps an idle one', () => {
    const pies = zonePies(ZONES)

    const all = pies.find((p) => p.key === 'all')
    expect(all.parts.map((p) => [p.key, p.value])).toEqual([
      ['search', 650],
      ['shelves', 250],
      ['catalog', 100],
    ])
    expect(pies.map((p) => [p.key, p.total])).toEqual([
      ['all', 1000],
      ['manual', 700],
      ['unified', 300],
      ['cpc', 0],
    ])
  })
})
