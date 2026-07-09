import { createPinia, setActivePinia } from 'pinia'

import { fetchSkuDetail, lookupSkus } from '@/modules/monitoring/api'
import { useMonitoringStore } from '@/modules/monitoring/store'

vi.mock('@/modules/monitoring/api', () => ({
  fetchSkuDetail: vi.fn(),
  lookupSkus: vi.fn(),
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
