import { createPinia, setActivePinia } from 'pinia'

import {
  fetchSkuDetail,
  fetchSkuSummary,
  fetchStockRange,
  getRefreshStatus,
  lookupSkus,
  refreshAllSkus,
  refreshSku,
  setDayAction,
} from '@/modules/monitoring/api'
import { useMonitoringStore } from '@/modules/monitoring/store'

vi.mock('@/modules/monitoring/api', () => ({
  fetchSkuDetail: vi.fn(),
  fetchSkuSummary: vi.fn(),
  fetchStockRange: vi.fn(),
  getRefreshStatus: vi.fn(),
  lookupSkus: vi.fn(),
  refreshAllSkus: vi.fn(),
  refreshSku: vi.fn(),
  setDayAction: vi.fn(),
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

describe('the campaign links after switching SKU', () => {
  /** A detail whose «Единая» group ran campaign `advertId` on 01.07. */
  function detailWith(nmId, advertId) {
    return {
      ...DETAIL,
      nm_id: nmId,
      matrix: { days: ['2026-07-01'], buckets: ['total'], rows: [{ key: 'views', values: [1] }] },
      matrix_base: {
        days: [{ day: '2026-07-01', buckets: { uni_search: { campaign_id: advertId } } }],
      },
    }
  }

  it('points at the new SKU’s campaign, not the first one opened', async () => {
    // Same window, different card: the table used to be patched in place and
    // kept the first card's links, so every link opened one campaign.
    fetchSkuDetail.mockResolvedValueOnce(detailWith(111, 9001))
    await store.fetchProductData('111')
    fetchSkuDetail.mockResolvedValueOnce(detailWith(222, 9002))

    await store.fetchProductData('222')

    expect(store.matrixView.campaigns).toEqual({
      nmId: 222,
      byDay: { '2026-07-01': { uni: 9002 } },
    })
  })
})

describe('the unit on the matrix', () => {
  const WITH_MATRIX = {
    ...DETAIL,
    price_currency: 'RUB',
    ad_currencies: ['KGS'],
    matrix: { days: ['2026-07-01'], buckets: ['total'], rows: [{ key: 'spend', values: [75] }] },
  }

  it('signs spend with the currency the detail states for the campaigns', async () => {
    // One workspace settles in KGS but is priced in RUB, and its campaigns bill in
    // KGS since 20.08.2026 — one workspace-wide unit misstated one of the two.
    fetchSkuDetail.mockResolvedValue(WITH_MATRIX)

    await store.fetchProductData('953770957')

    const spend = store.matrixView.rows.find((row) => row.key === 'spend')
    expect(spend.label).toBe('Затраты')
    expect(spend.cells.find((cell) => cell.bucket === 'total').display).toBe('KGS 75')
  })

  it('prints spend with no sign while WB has named no currency', async () => {
    // A SKU with no charged campaign: no sign, not a guess.
    fetchSkuDetail.mockResolvedValue({ ...WITH_MATRIX, ad_currencies: [] })

    await store.fetchProductData('953770957')

    const spend = store.matrixView.rows.find((row) => row.key === 'spend')
    expect(spend.cells.find((cell) => cell.bucket === 'total').display).toBe('75')
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
    fetchStockRange.mockResolvedValue({ days: [] })
    await store.fetchProductData('953770957')
    vi.clearAllMocks()
    fetchSkuDetail.mockResolvedValue(DETAIL)
    fetchStockRange.mockResolvedValue({ days: [] })
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
      // Past the 30-minute ceiling. It grew from 6 when «Обновить» stopped
      // being a subset of the nightly pass: it now pulls the account-wide sale
      // feed and the 22-day cohort pass, whose paced requests take ~7 minutes.
      await vi.advanceTimersByTimeAsync(31 * 60_000)
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
    // all reported as «не завершилось за отведённое время», which is why users
    // concluded «Обновить» never works. A poll ceiling BELOW the backend's own
    // limit turns every slow success into a visible failure.
    vi.useFakeTimers()
    try {
      refreshSku.mockResolvedValue({ task_id: 'task-slow' })
      let elapsed = 0
      // Ten minutes: past the OLD 6-minute ceiling, and a realistic duration
      // now that one refresh includes the cohort pass. A test that only proved
      // the store waits 200s would no longer prove anything about the ceiling
      // it is named after.
      const slowHarvestMs = 10 * 60_000
      getRefreshStatus.mockImplementation(async () => {
        elapsed = Date.now() - startedAt
        return elapsed < slowHarvestMs ? { ready: false } : { ready: true, successful: true }
      })
      const startedAt = Date.now()

      const pending = store.refreshFromWb()
      await vi.advanceTimersByTimeAsync(slowHarvestMs + 10_000)
      await pending
    } finally {
      vi.useRealTimers()
    }

    expect(fetchSkuDetail).toHaveBeenCalled()
    expect(store.actionError).toBeNull()
  })

  it('puts stage-1 data on screen without waiting for the buyout pass', async () => {
    // THE POINT OF STAGING. The backend commits advertising, funnel, stocks and
    // prices before it starts the ~7-minute buyout-cohort pass, and reports the
    // stage boundary. Redrawing there is what lets the seller read the numbers
    // they came for while the slow half is still running — waiting for `ready`
    // would put the whole wait in front of data that is already in the database.
    refreshSku.mockResolvedValue({ task_id: 'task-staged' })
    let redrawsBeforeCompletion = null
    getRefreshStatus
      .mockResolvedValueOnce({ ready: false, stage: 1, percent: 0, message: 'Собираем…' })
      .mockResolvedValueOnce({
        ready: false,
        stage: 2,
        percent: 40,
        message: 'Считаем проценты выкупа…',
      })
      .mockImplementationOnce(async () => {
        // Sampled on the poll that ENDS the run: anything counted here was
        // drawn while the buyout pass was still going.
        redrawsBeforeCompletion = fetchSkuDetail.mock.calls.length
        return { ready: true, successful: true, failed_sources: [] }
      })

    vi.useFakeTimers()
    try {
      const pending = store.refreshFromWb()
      await vi.advanceTimersByTimeAsync(5_000)
      await pending
    } finally {
      vi.useRealTimers()
    }

    // The stage boundary redrew the table before the task was done.
    expect(redrawsBeforeCompletion).toBe(1)
    // And again at the end, when the buyout percentages land.
    expect(fetchSkuDetail.mock.calls.length).toBe(2)
    expect(store.actionError).toBeNull()
  })

  it('surfaces the backend’s own progress line rather than inventing one', async () => {
    // The message is rendered verbatim under the button, so it must come from
    // the task. Assembling it here would let the UI claim a stage is running
    // that the backend has not reached.
    refreshSku.mockResolvedValue({ task_id: 'task-progress' })
    let seen = null
    getRefreshStatus
      .mockResolvedValueOnce({ ready: false, stage: 2, percent: 40, message: 'Считаем выкупы…' })
      .mockImplementationOnce(async () => {
        seen = { ...store.refreshProgress }
        return { ready: true, successful: true, failed_sources: [] }
      })

    vi.useFakeTimers()
    try {
      const pending = store.refreshFromWb()
      await vi.advanceTimersByTimeAsync(5_000)
      await pending
    } finally {
      vi.useRealTimers()
    }

    expect(seen).toEqual({ percent: 40, message: 'Считаем выкупы…' })
    // Cleared when the run ends, so a finished refresh leaves no stale bar.
    expect(store.refreshProgress).toBeNull()
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

describe('refreshAllFromWb', () => {
  beforeEach(() => {
    fetchSkuSummary.mockResolvedValue({ items: [] })
  })

  it('refreshes the SKU list once the bulk harvest reports success', async () => {
    // The button lives on the empty/list view too, so a run with no SKU open
    // must still complete and repaint the list — not depend on a current SKU.
    refreshAllSkus.mockResolvedValue({ task_id: 'task-all-1' })
    getRefreshStatus
      .mockResolvedValueOnce({ ready: false, successful: false })
      .mockResolvedValueOnce({ ready: true, successful: true, failed_sources: [] })

    await store.refreshAllFromWb()

    expect(refreshAllSkus).toHaveBeenCalledOnce()
    expect(fetchSkuSummary).toHaveBeenCalled()
    expect(store.allRefreshError).toBeNull()
    expect(store.allRefreshing).toBe(false)
  })

  it('surfaces an error and does not repaint when the task fails', async () => {
    refreshAllSkus.mockResolvedValue({ task_id: 'task-all-2' })
    getRefreshStatus.mockResolvedValue({ ready: true, successful: false })

    await store.refreshAllFromWb()

    expect(fetchSkuSummary).not.toHaveBeenCalled()
    expect(store.allRefreshError).toBeTruthy()
    expect(store.allRefreshing).toBe(false)
  })

  it('surfaces the error when there is nothing to refresh (404 on enqueue)', async () => {
    // An empty workspace returns 404 from the enqueue endpoint; the message must
    // reach the button's own error slot, not the metrics table's actionError.
    refreshAllSkus.mockRejectedValue(new Error('В воркспейсе нет ни одного SKU для обновления.'))

    await store.refreshAllFromWb()

    expect(store.allRefreshError).toBeTruthy()
    expect(store.actionError).toBeNull()
    expect(store.allRefreshing).toBe(false)
  })
})

describe('saveDayAction while the same day is already saving', () => {
  const DAY = '2026-10-09'

  /** A PUT that stays in flight until the test resolves it, echoing the body. */
  function heldSave() {
    let release
    const held = new Promise((resolve) => {
      release = resolve
    })
    setDayAction.mockImplementationOnce(async (_nmId, _iso, body) => {
      await held
      return { action: body }
    })
    return () => release()
  }

  beforeEach(() => {
    setDayAction.mockImplementation(async (_nmId, _iso, body) => ({ action: body }))
    store.currentProduct = { nm_id: 1948347102, day_actions: {} }
  })

  it('sends a change made mid-save once that save lands, on top of it', async () => {
    const release = heldSave()

    const first = store.saveDayAction(DAY, { first_rk_type: 'uni', first_rk_budget: 4000 })
    await store.saveDayAction(DAY, { second_rk_type: 'manual_search' })
    release()
    await first

    expect(setDayAction).toHaveBeenCalledTimes(2)
    expect(setDayAction).toHaveBeenLastCalledWith(1948347102, DAY, {
      first_rk_type: 'uni',
      first_rk_budget: 4000,
      second_rk_type: 'manual_search',
    })
    expect(store.currentProduct.day_actions[DAY].second_rk_type).toBe('manual_search')
    expect(store.actionSavingDays.has(DAY)).toBe(false)
  })

  it('merges several mid-save changes into one follow-up request', async () => {
    const release = heldSave()

    const first = store.saveDayAction(DAY, { first_rk_type: 'uni' })
    await store.saveDayAction(DAY, { second_rk_type: 'manual_search' })
    await store.saveDayAction(DAY, { second_rk_budget: 8000 })
    release()
    await first

    expect(setDayAction).toHaveBeenCalledTimes(2)
    expect(store.currentProduct.day_actions[DAY]).toEqual({
      first_rk_type: 'uni',
      second_rk_type: 'manual_search',
      second_rk_budget: 8000,
    })
  })

  it('still sends the queued change when the SKU on screen changed mid-save', async () => {
    const release = heldSave()

    const first = store.saveDayAction(DAY, { first_rk_type: 'uni' })
    store.currentProduct = { nm_id: 1944299862, day_actions: {} }
    await store.saveDayAction(DAY, { price_change: 'up' })
    release()
    await first

    expect(setDayAction).toHaveBeenLastCalledWith(1944299862, DAY, { price_change: 'up' })
    expect(store.currentProduct.day_actions[DAY]).toEqual({ price_change: 'up' })
  })
})
