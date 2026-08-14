import { createPinia, setActivePinia } from 'pinia'

import { fetchSkuClusters, probeSkuSearchPosition } from '@/modules/monitoring/api'
import { useClusterSearchStore } from '@/modules/monitoring/clusterStore'

vi.mock('@/modules/monitoring/api', () => ({
  fetchSkuClusters: vi.fn(),
  probeSkuSearchPosition: vi.fn(),
}))

const NM_ID = 953770957

const CLUSTERS = {
  nm_id: NM_ID,
  window: { start: '2026-08-01', end: '2026-08-13' },
  items: [{ cluster: 'носки мужские', views: 1000, clicks: 50, avg_position: 6.2 }],
}

const POSITION = {
  nm_id: NM_ID,
  query: 'носки',
  normalized_query: 'мужские носки',
  checked_at: '2026-08-14T09:00:00Z',
  total_found: 1000,
  positions_scanned: 300,
  truncated: true,
  position: 7,
  page: 1,
  position_on_page: 7,
  other_skus: [],
}

let store

beforeEach(() => {
  setActivePinia(createPinia())
  store = useClusterSearchStore()
  vi.clearAllMocks()
  fetchSkuClusters.mockResolvedValue(CLUSTERS)
  probeSkuSearchPosition.mockResolvedValue(POSITION)
})

describe('the cluster half', () => {
  it('loads the page SKU’s clusters for the page window', async () => {
    await store.loadForSku(NM_ID, { from: '2026-08-01', to: '2026-08-13' })

    expect(fetchSkuClusters).toHaveBeenCalledWith(
      NM_ID,
      { date_from: '2026-08-01', date_to: '2026-08-13' },
      expect.anything(),
    )
    expect(store.clusters).toHaveLength(1)
  })

  it('reports a failure instead of showing an empty cluster list', async () => {
    // «Реклама не показывалась» and «запрос не выполнился» lead a seller to
    // opposite decisions, so a failure is never rendered as "no clusters".
    fetchSkuClusters.mockRejectedValue({ response: { status: 500 } })

    await store.loadForSku(NM_ID, {})

    expect(store.clusters).toEqual([])
    expect(store.clustersError).not.toBe('')
    expect(store.loaded).toBe(true)
  })

  it('leaves a cancelled load without an error message', async () => {
    // Switching SKU aborts the previous load; surfacing that as an error would
    // flash a failure on every navigation.
    fetchSkuClusters.mockRejectedValue({ code: 'ERR_CANCELED' })

    await store.loadForSku(NM_ID, {})

    expect(store.clustersError).toBe('')
  })
})

describe('the live position half', () => {
  it('checks the phrase against the SKU currently loaded', async () => {
    await store.loadForSku(NM_ID, {})

    await store.checkPosition('  носки  ')

    expect(probeSkuSearchPosition).toHaveBeenCalledWith(
      NM_ID,
      'носки',
      { refresh: false },
      expect.anything(),
    )
    expect(store.position.position).toBe(7)
  })

  it('does nothing without a phrase or without a SKU', async () => {
    // WB has no ranking for an empty phrase, and the endpoint is rate-limited
    // per IP — spending that budget on nothing slows down real checks.
    await store.checkPosition('носки')
    await store.loadForSku(NM_ID, {})
    await store.checkPosition('   ')

    expect(probeSkuSearchPosition).not.toHaveBeenCalled()
  })

  it('keeps the cluster table when the probe is throttled', async () => {
    // The halves have different provenance and different failure modes: a
    // throttled WB must not blank out a month of harvested history.
    probeSkuSearchPosition.mockRejectedValue({ response: { status: 502 } })
    await store.loadForSku(NM_ID, {})

    await store.checkPosition('носки')

    expect(store.clusters).toHaveLength(1)
    expect(store.position).toBeNull()
    expect(store.positionError).not.toBe('')
  })

  it('drops a rank that belonged to the previous SKU', async () => {
    // The number is about one card. Carrying it onto the next SKU's page would
    // read as that card's position, which it never was.
    await store.loadForSku(NM_ID, {})
    await store.checkPosition('носки')

    await store.loadForSku(144178006, {})

    expect(store.position).toBeNull()
  })

  it('asks the backend to bypass its cache on an explicit re-check', async () => {
    await store.loadForSku(NM_ID, {})

    await store.checkPosition('носки', { refresh: true })

    expect(probeSkuSearchPosition).toHaveBeenCalledWith(
      NM_ID,
      'носки',
      { refresh: true },
      expect.anything(),
    )
  })
})
