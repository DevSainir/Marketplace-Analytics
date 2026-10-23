import { createPinia, setActivePinia } from 'pinia'

import { fetchSkuClusters } from '@/modules/monitoring/api'
import { useClusterSearchStore } from '@/modules/monitoring/clusterStore'

vi.mock('@/modules/monitoring/api', () => ({
  fetchSkuClusters: vi.fn(),
}))

const NM_ID = 953770957

const CLUSTERS = {
  nm_id: NM_ID,
  window: { start: '2026-08-01', end: '2026-08-13' },
  items: [{ cluster: "men's socks", views: 1000, clicks: 50, avg_position: 6.2 }],
}

let store

beforeEach(() => {
  setActivePinia(createPinia())
  store = useClusterSearchStore()
  vi.clearAllMocks()
  fetchSkuClusters.mockResolvedValue(CLUSTERS)
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
    // "the ads were not shown" and "the request failed" lead a seller to
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
