import { createPinia, setActivePinia } from 'pinia'

import {
  fetchSkuDetail,
  fetchSkuSummary,
  fetchStockDay,
  getRefreshStatus,
  lookupSkus,
  refreshSku,
} from '@/modules/monitoring/api'
import { useMonitoringStore } from '@/modules/monitoring/store'

vi.mock('@/modules/monitoring/api', () => ({
  fetchSkuDetail: vi.fn(),
  fetchSkuSummary: vi.fn(),
  fetchStockDay: vi.fn(),
  getRefreshStatus: vi.fn(),
  lookupSkus: vi.fn(),
  refreshSku: vi.fn(),
}))

const DETAIL = {
  nm_id: 953770957,
  vendor_code: 'M-TRX01-BLK',
  funnel_totals: { cart_count: 1449, order_count: 747 },
  advertising: [
    { clicks: 4000, spend: 60000 },
    { clicks: 462, spend: 3746 },
  ],
  stock: { total_quantity: 2952 },
}

let store

beforeEach(() => {
  setActivePinia(createPinia())
  store = useMonitoringStore()
  vi.clearAllMocks()
})

describe('fetchProductData with a numeric SKU', () => {
  it('loads the detail directly, without a lookup', async () => {
    fetchSkuDetail.mockResolvedValue(DETAIL)

    await store.fetchProductData('953770957', { date_from: '2026-07-01', date_to: '2026-07-07' })

    expect(lookupSkus).not.toHaveBeenCalled()
    expect(fetchSkuDetail).toHaveBeenCalledWith(
      953770957,
      { date_from: '2026-07-01', date_to: '2026-07-07' },
      expect.any(AbortSignal),
    )
    expect(store.currentProduct).toEqual(DETAIL)
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })

  it('derives totals from funnel_totals and campaign sums', async () => {
    fetchSkuDetail.mockResolvedValue(DETAIL)

    await store.fetchProductData('953770957')

    expect(store.totalCarts).toBe(1449)
    expect(store.totalOrders).toBe(747)
    expect(store.totalAdClicks).toBe(4462)
    expect(store.totalAdSpend).toBe(63746)
    expect(store.isOutOfStock).toBe(false)
  })

  it('maps request failures onto the error state', async () => {
    fetchSkuDetail.mockRejectedValue(new Error('boom'))

    await store.fetchProductData('42')

    expect(store.currentProduct).toBeNull()
    expect(store.error).toBe('boom')
    expect(store.loading).toBe(false)
  })
})

describe('fetchProductData with a vendor code', () => {
  it('resolves an exact match case-insensitively', async () => {
    lookupSkus.mockResolvedValue({
      count: 2,
      items: [
        { nm_id: 1, vendor_code: 'M-TRX01-BEJ' },
        { nm_id: 2, vendor_code: 'M-TRX01-BLK' },
      ],
    })
    fetchSkuDetail.mockResolvedValue(DETAIL)

    await store.fetchProductData('m-trx01-blk')

    expect(fetchSkuDetail).toHaveBeenCalledWith(2, expect.anything(), expect.any(AbortSignal))
    expect(store.lookupMatches).toEqual([])
  })

  it('uses a single hit as-is', async () => {
    lookupSkus.mockResolvedValue({ count: 1, items: [{ nm_id: 7, vendor_code: 'M-LNX01-BLU' }] })
    fetchSkuDetail.mockResolvedValue(DETAIL)

    await store.fetchProductData('M-LNX')

    expect(fetchSkuDetail).toHaveBeenCalledWith(7, expect.anything(), expect.any(AbortSignal))
  })

  it('exposes ambiguous matches for the user instead of guessing', async () => {
    const items = [
      { nm_id: 1, vendor_code: 'M-TRX01-BEJ' },
      { nm_id: 2, vendor_code: 'M-TRX01-BLK' },
      { nm_id: 3, vendor_code: 'M-TRX01-CHK' },
    ]
    lookupSkus.mockResolvedValue({ count: 3, items })

    await store.fetchProductData('M-TRX')

    expect(fetchSkuDetail).not.toHaveBeenCalled()
    expect(store.lookupMatches).toEqual(items)
    expect(store.currentProduct).toBeNull()
    expect(store.error).toBeNull()
  })

  it('reports an empty result as notFound, not as an error', async () => {
    lookupSkus.mockResolvedValue({ count: 0, items: [] })

    await store.fetchProductData('NOPE')

    expect(fetchSkuDetail).not.toHaveBeenCalled()
    expect(store.notFound).toBe('NOPE')
    expect(store.error).toBeNull()
    expect(store.currentProduct).toBeNull()
  })

  it('selectSku loads a chosen match with the searched window', async () => {
    lookupSkus.mockResolvedValue({
      count: 2,
      items: [
        { nm_id: 1, vendor_code: 'M-TRX01-BEJ' },
        { nm_id: 2, vendor_code: 'M-TRX01-CHK' },
      ],
    })
    await store.fetchProductData('M-TRX', { date_from: '2026-07-01', date_to: '2026-07-07' })

    fetchSkuDetail.mockResolvedValue(DETAIL)
    await store.selectSku(2)

    expect(fetchSkuDetail).toHaveBeenCalledWith(
      2,
      { date_from: '2026-07-01', date_to: '2026-07-07' },
      expect.any(AbortSignal),
    )
    expect(store.lookupMatches).toEqual([])
  })
})

describe('fetchSkuList', () => {
  const SUMMARY = {
    count: 2,
    total: 2,
    items: [
      { nm_id: 1, vendor_code: 'M-TRX01-BEJ' },
      { nm_id: 2, vendor_code: 'M-TRX01-BLK' },
    ],
  }

  it('loads the window summary into skuList (one 500-item page)', async () => {
    fetchSkuSummary.mockResolvedValue(SUMMARY)

    await store.fetchSkuList({ date_from: '2026-07-01', date_to: '2026-07-07' })

    expect(fetchSkuSummary).toHaveBeenCalledWith(
      { date_from: '2026-07-01', date_to: '2026-07-07', limit: 500 },
      expect.any(AbortSignal),
    )
    expect(store.skuList).toEqual(SUMMARY.items)
    expect(store.skuListLoading).toBe(false)
    expect(store.skuListError).toBeNull()
  })

  it('maps list failures onto skuListError without touching the detail state', async () => {
    fetchSkuDetail.mockResolvedValue(DETAIL)
    await store.fetchProductData('953770957')

    fetchSkuSummary.mockRejectedValue(new Error('boom'))
    await store.fetchSkuList()

    expect(store.skuList).toEqual([])
    expect(store.skuListError).toBe('boom')
    expect(store.currentProduct).toEqual(DETAIL) // detail search untouched
    expect(store.error).toBeNull()
  })

  it('aborts the in-flight list fetch when a new one starts', async () => {
    let firstSignal
    fetchSkuSummary
      .mockImplementationOnce((params, signal) => {
        firstSignal = signal
        return new Promise(() => {}) // never settles: the abort is what ends it
      })
      .mockResolvedValueOnce(SUMMARY)

    store.fetchSkuList()
    await store.fetchSkuList()

    expect(firstSignal.aborted).toBe(true)
    expect(store.skuList).toEqual(SUMMARY.items)
  })

  it('reset leaves the loaded list intact (it is window-, not search-scoped)', async () => {
    fetchSkuSummary.mockResolvedValue(SUMMARY)
    await store.fetchSkuList()

    store.reset()

    expect(store.skuList).toEqual(SUMMARY.items)
  })
})

describe('race protection', () => {
  it('discards a slow stale response that resolves after a newer search', async () => {
    let resolveFirst
    fetchSkuDetail
      .mockImplementationOnce(() => new Promise((resolve) => (resolveFirst = resolve)))
      .mockResolvedValueOnce({ ...DETAIL, nm_id: 222 })

    const first = store.fetchProductData('111')
    const second = store.fetchProductData('222')
    await second

    resolveFirst({ ...DETAIL, nm_id: 111 })
    await first

    expect(store.currentProduct.nm_id).toBe(222)
    expect(store.loading).toBe(false)
  })

  it('discards a stale rejection so it cannot clobber newer data', async () => {
    let rejectFirst
    fetchSkuDetail
      .mockImplementationOnce(() => new Promise((_, reject) => (rejectFirst = reject)))
      .mockResolvedValueOnce({ ...DETAIL, nm_id: 222 })

    const first = store.fetchProductData('111')
    const second = store.fetchProductData('222')
    await second

    rejectFirst(new Error('stale failure'))
    await first

    expect(store.currentProduct.nm_id).toBe(222)
    expect(store.error).toBeNull()
  })

  it('discards a slow vendor-code lookup that resolves empty after a newer search', async () => {
    let resolveLookup
    lookupSkus.mockImplementationOnce(() => new Promise((resolve) => (resolveLookup = resolve)))
    fetchSkuDetail.mockResolvedValueOnce({ ...DETAIL, nm_id: 222 })

    const first = store.fetchProductData('M-GONE')
    const second = store.fetchProductData('222')
    await second

    resolveLookup({ count: 0, items: [] }) // stale «ничего не найдено»
    await first

    expect(store.currentProduct.nm_id).toBe(222)
    expect(store.notFound).toBeNull()
    expect(store.error).toBeNull()
  })

  it('discards stale ambiguous lookup matches so they cannot clobber newer data', async () => {
    let resolveLookup
    lookupSkus.mockImplementationOnce(() => new Promise((resolve) => (resolveLookup = resolve)))
    fetchSkuDetail.mockResolvedValueOnce({ ...DETAIL, nm_id: 222 })

    const first = store.fetchProductData('M-TRX')
    const second = store.fetchProductData('222')
    await second

    resolveLookup({
      count: 2,
      items: [
        { nm_id: 1, vendor_code: 'M-TRX01-BEJ' },
        { nm_id: 2, vendor_code: 'M-TRX01-BLK' },
      ],
    })
    await first

    expect(store.currentProduct.nm_id).toBe(222)
    expect(store.lookupMatches).toEqual([])
  })
})

describe('request cancellation', () => {
  it('aborts the in-flight request when a new search starts', async () => {
    let firstSignal
    fetchSkuDetail
      .mockImplementationOnce((nmId, params, signal) => {
        firstSignal = signal
        return new Promise(() => {}) // never settles: the abort is what ends it
      })
      .mockResolvedValueOnce({ ...DETAIL, nm_id: 222 })

    store.fetchProductData('111')
    await store.fetchProductData('222')

    expect(firstSignal.aborted).toBe(true)
    expect(store.currentProduct.nm_id).toBe(222)
  })

  it('treats an axios cancellation as silence, not an error', async () => {
    const canceled = new Error('canceled')
    canceled.code = 'ERR_CANCELED'
    canceled.name = 'CanceledError'
    fetchSkuDetail.mockRejectedValue(canceled)

    await store.fetchProductData('111')

    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('reset aborts the in-flight search and clears all state', async () => {
    let signal
    fetchSkuDetail.mockImplementationOnce((nmId, params, s) => {
      signal = s
      // Mimic axios: the request rejects with a CanceledError on abort.
      return new Promise((_, reject) => {
        s.addEventListener('abort', () => {
          const err = new Error('canceled')
          err.code = 'ERR_CANCELED'
          err.name = 'CanceledError'
          reject(err)
        })
      })
    })

    const pending = store.fetchProductData('111')
    store.reset()
    await pending

    expect(signal.aborted).toBe(true)
    expect(store.loading).toBe(false)
    expect(store.currentProduct).toBeNull()
    expect(store.error).toBeNull()
    expect(store.notFound).toBeNull()
    expect(store.lookupMatches).toEqual([])
  })
})

describe('refreshFromWb', () => {
  beforeEach(async () => {
    fetchSkuDetail.mockResolvedValue(DETAIL)
    fetchStockDay.mockResolvedValue({ stock: null })
    await store.fetchProductData('953770957')
    vi.clearAllMocks()
    fetchSkuDetail.mockResolvedValue(DETAIL)
    fetchStockDay.mockResolvedValue({ stock: null })
  })

  it('re-fetches the detail once the harvest task reports success', async () => {
    refreshSku.mockResolvedValue({ task_id: 'task-1' })
    getRefreshStatus
      .mockResolvedValueOnce({ ready: false, successful: false })
      .mockResolvedValueOnce({ ready: true, successful: true })

    await store.refreshFromWb()

    expect(fetchSkuDetail).toHaveBeenCalled()
    expect(store.actionError).toBeNull()
    expect(store.matrixRefreshing).toBe(false)
  })

  it('surfaces an error when the task finishes unsuccessfully', async () => {
    refreshSku.mockResolvedValue({ task_id: 'task-2' })
    getRefreshStatus.mockResolvedValue({ ready: true, successful: false })

    await store.refreshFromWb()

    expect(fetchSkuDetail).not.toHaveBeenCalled()
    expect(store.actionError).toBeTruthy()
  })

  it('does NOT report success when the poll ceiling runs out', async () => {
    // The bug this pins: exhausting the ceiling used to fall through to the
    // re-fetch, clearing the spinner and presenting unrefreshed numbers as a
    // completed refresh. A task that never becomes ready must surface an error
    // and must not re-fetch.
    //
    // Fake timers so the minutes of real polling cost no wall-clock here;
    // `advanceTimersByTimeAsync` flushes the awaited status calls between ticks.
    vi.useFakeTimers()
    try {
      refreshSku.mockResolvedValue({ task_id: 'task-3' })
      getRefreshStatus.mockResolvedValue({ ready: false, successful: false })

      const pending = store.refreshFromWb()
      await vi.advanceTimersByTimeAsync(7 * 60_000)
      await pending
    } finally {
      vi.useRealTimers()
    }

    expect(fetchSkuDetail).not.toHaveBeenCalled()
    expect(store.actionError).toMatch(/не завершилось за отведённое время/i)
    expect(store.matrixRefreshing).toBe(false)
  })

  it('waits out a slow harvest instead of calling it a timeout', async () => {
    // THE 2026-07-30 REGRESSION. The ceiling was 200 polls x 600ms = 120s while
    // the backend legitimately takes up to ~4 minutes when a cohort pass is
    // competing for WB's rate budget. Harvests that succeeded in 144-198s were
    // all reported as "не завершилось за отведённое время", which is why users
    // concluded «Обновить» never works. A poll ceiling BELOW the backend's own
    // limit turns every slow success into a visible failure.
    vi.useFakeTimers()
    try {
      refreshSku.mockResolvedValue({ task_id: 'task-slow' })
      let elapsed = 0
      getRefreshStatus.mockImplementation(async () => {
        elapsed = Date.now() - startedAt
        return elapsed < 200_000 ? { ready: false } : { ready: true, successful: true }
      })
      const startedAt = Date.now()

      const pending = store.refreshFromWb()
      await vi.advanceTimersByTimeAsync(210_000)
      await pending
    } finally {
      vi.useRealTimers()
    }

    expect(fetchSkuDetail).toHaveBeenCalled()
    expect(store.actionError).toBeNull()
  })

  it('says which WB sources were withheld when the harvest was partial', async () => {
    // A harvest tolerates a partial WB outage, so `successful` stays true while
    // the funnel never arrived and the table redraws its previous numbers. Left
    // unsaid, that is indistinguishable from a button that does nothing — which
    // is precisely how the incident presented to users.
    refreshSku.mockResolvedValue({ task_id: 'task-partial' })
    getRefreshStatus.mockResolvedValue({
      ready: true,
      successful: true,
      failed_sources: ['sales-funnel', 'stocks'],
    })

    await store.refreshFromWb()

    expect(fetchSkuDetail).toHaveBeenCalled()
    expect(store.actionError).toBeNull()
    expect(store.actionWarning).toMatch(/воронку продаж/i)
    expect(store.actionWarning).toMatch(/остатки/i)
  })

  it('clears the partial-refresh warning once WB serves everything', async () => {
    refreshSku.mockResolvedValue({ task_id: 'task-partial' })
    getRefreshStatus.mockResolvedValue({
      ready: true,
      successful: true,
      failed_sources: ['sales-funnel'],
    })
    await store.refreshFromWb()
    getRefreshStatus.mockResolvedValue({ ready: true, successful: true, failed_sources: [] })

    await store.refreshFromWb()

    expect(store.actionWarning).toBeNull()
  })

  it('reports a fully served refresh without any warning', async () => {
    refreshSku.mockResolvedValue({ task_id: 'task-ok' })
    getRefreshStatus.mockResolvedValue({ ready: true, successful: true, failed_sources: [] })

    await store.refreshFromWb()

    expect(store.actionWarning).toBeNull()
    expect(store.actionError).toBeNull()
  })
})
