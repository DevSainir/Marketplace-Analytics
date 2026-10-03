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
      [1, 'Единая ставка', 300],
      [2, 'Поиск', 50],
      [2, 'Полки', 250],
      [2, 'Каталог', 0],
    ])
  })

  it('shows the unified catalogue as unknown, not as a zero', () => {
    // WB never splits it out of «Полки»; a 0 would claim it was measured.
    const catalog = zoneRows(ZONES).at(-1)

    expect(catalog).toMatchObject({ unknown: true, share: null })
  })

  it('leaves out the branches that spent nothing', () => {
    const rows = zoneRows([{ zone: 'cpc_search', spend: '10', bonus: '0' }])

    expect(rows.map((r) => r.label)).toEqual(['CPC', 'Поиск'])
  })
})

describe('zonePies', () => {
  it('splits every pie by search, shelves and catalogue, the whole pie summing them all', () => {
    const pies = zonePies(ZONES)

    const all = pies.find((p) => p.key === 'all')
    expect(all.parts.map((p) => [p.key, p.value])).toEqual([
      ['search', 650],
      ['shelves', 250],
      ['catalog', 100],
    ])
    expect(pies.map((p) => p.key)).toEqual(['all', 'manual', 'unified'])
  })
})
