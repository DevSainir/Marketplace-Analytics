import { createPinia, setActivePinia } from 'pinia'

import {
  fetchPinnedKeywords,
  fetchSkuClusters,
  fetchSkuPositionCheck,
  fetchSkuSearchPosition,
  getRefreshStatus,
  refreshAllPositions,
  startSkuPositionCheck,
} from '@/modules/monitoring/api'
import { useClusterSearchStore } from '@/modules/monitoring/clusterStore'

vi.mock('@/modules/monitoring/api', () => ({
  fetchPinnedKeywords: vi.fn(),
  fetchSkuClusters: vi.fn(),
  fetchSkuPositionCheck: vi.fn(),
  fetchSkuSearchPosition: vi.fn(),
  getRefreshStatus: vi.fn(),
  pinKeyword: vi.fn(),
  refreshAllPositions: vi.fn(),
  startSkuPositionCheck: vi.fn(),
  unpinKeyword: vi.fn(),
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
  fetchSkuSearchPosition.mockResolvedValue(POSITION)
  fetchSkuPositionCheck.mockResolvedValue(null)
  startSkuPositionCheck.mockResolvedValue({ task_id: 'check-1', query: 'носки' })
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
  it('queues a check for the SKU currently loaded', async () => {
    await store.loadForSku(NM_ID, {})

    await store.checkPosition('  носки  ')

    expect(startSkuPositionCheck).toHaveBeenCalledWith(NM_ID, 'носки')
    // Nothing is read until the check reports ready: showing the previous sample
    // under a running spinner reads as the new answer.
    expect(store.positionLoading).toBe(true)
  })

  it('does nothing without a phrase or without a SKU', async () => {
    // WB has no ranking for an empty phrase, and every attempt spends a slot of a
    // budget that refuses roughly every second request.
    await store.checkPosition('носки')
    await store.loadForSku(NM_ID, {})
    await store.checkPosition('   ')

    expect(startSkuPositionCheck).not.toHaveBeenCalled()
  })

  it('keeps the cluster table when the check cannot even be queued', async () => {
    // The halves have different provenance and different failure modes: a broken
    // check must not blank out a month of harvested history.
    startSkuPositionCheck.mockRejectedValue({ response: { status: 502 } })
    await store.loadForSku(NM_ID, {})

    await store.checkPosition('носки')

    expect(store.clusters).toHaveLength(1)
    expect(store.position).toBeNull()
    expect(store.positionError).not.toBe('')
  })

  it('re-attaches to a check that was already running when the page loaded', async () => {
    // The point of moving the work into a task: a seller who leaves and comes
    // back must see the check still running, not an empty panel. The task id
    // lives server-side, so a fresh tab finds it.
    fetchSkuPositionCheck.mockResolvedValue({
      task_id: 'check-9',
      query: 'носки мужские',
      ready: false,
      successful: false,
    })

    await store.loadForSku(NM_ID, {})
    await vi.waitFor(() => expect(store.positionLoading).toBe(true))

    expect(store.query).toBe('носки мужские')
  })

  it('collects the result of a check that finished while nobody was looking', async () => {
    fetchSkuPositionCheck.mockResolvedValue({
      task_id: 'check-9',
      query: 'носки',
      ready: true,
      successful: true,
    })

    await store.loadForSku(NM_ID, {})
    await vi.waitFor(() => expect(store.position?.position).toBe(7))

    expect(store.positionLoading).toBe(false)
    expect(fetchSkuSearchPosition).toHaveBeenCalledWith(NM_ID, 'носки')
  })

  it('explains a finished check that WB never answered', async () => {
    // `successful: false` is not "ranks nowhere" — the pins keep their numbers and
    // the panel has to say why nothing moved.
    fetchSkuPositionCheck.mockResolvedValue({
      task_id: 'check-9',
      query: 'носки',
      ready: true,
      successful: false,
    })

    await store.loadForSku(NM_ID, {})
    await vi.waitFor(() => expect(store.positionError).not.toBe(''))

    expect(store.position).toBeNull()
    expect(fetchSkuSearchPosition).not.toHaveBeenCalled()
  })

  it('drops a rank that belonged to the previous SKU', async () => {
    // The number is about one card. Carrying it onto the next SKU's page would
    // read as that card's position, which it never was.
    fetchSkuPositionCheck.mockResolvedValue(null)
    await store.loadForSku(NM_ID, {})
    store.position = POSITION

    await store.loadForSku(144178006, {})

    expect(store.position).toBeNull()
  })
})

describe('refreshAllPinned', () => {
  it('reports the phrases WB refused instead of claiming success', async () => {
    // Prod 2026-08-17: one pinned phrase, two 429s, the task returned SUCCESS
    // having updated nothing, and the panel said «Позиции обновлены.» over an
    // unchanged timestamp. The run's own `successful` flag cannot carry this.
    vi.useFakeTimers()
    fetchPinnedKeywords.mockResolvedValue({
      items: [
        { keyword: 'штаны бананы мужские', position: 26, checked_at: '2026-08-17T05:02:00Z' },
      ],
    })
    refreshAllPositions.mockResolvedValue({ task_id: 'abc', pinned_count: 1 })
    getRefreshStatus.mockResolvedValue({
      ready: true,
      successful: true,
      failed_sources: ['штаны бананы мужские'],
    })

    await store.loadForSku(NM_ID, {})
    await store.refreshAllPinned()
    await vi.advanceTimersByTimeAsync(6000)

    expect(store.refreshMessage).toContain('WB ограничил частоту')
    expect(store.refreshMessage).toContain('штаны бананы мужские')
    expect(store.refreshMessage).not.toContain('Позиции обновлены')
    vi.useRealTimers()
  })
})
