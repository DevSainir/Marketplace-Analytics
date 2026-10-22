/**
 * The monitoring sandbox reads the workspace's own data, read-only.
 *
 * It replaced synthesised fixtures, so what is pinned here is what made the
 * fixtures unnecessary: it opens on a real SKU of the workspace, loads the same
 * three things the page renders (the window, its stock, a year for the long
 * chart), and a failure is a line on the page rather than an empty sandbox.
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  fetchPinnedSkus,
  fetchSkuDetail,
  fetchSkuSummary,
  fetchStockRange,
} from '@/modules/labs/api'
import { useLabMonitoringStore } from '@/modules/labs/store'

vi.mock('@/modules/labs/api', () => ({
  fetchPinnedSkus: vi.fn(),
  fetchSkuDetail: vi.fn(),
  fetchSkuSummary: vi.fn(),
  fetchStockRange: vi.fn(),
}))

const LISTED = { nm_id: 9000000106, vendor_code: 'W-TSH05-WHT', title: 'Футболка' }
const PINNED = { nm_id: 9000000101, vendor_code: 'M-TRX01-BLK', color: '#E3DEFF' }

let store

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  fetchSkuSummary.mockResolvedValue({ items: [LISTED] })
  fetchPinnedSkus.mockResolvedValue({ items: [PINNED] })
  fetchSkuDetail.mockImplementation((nmId) => Promise.resolve({ nm_id: nmId }))
  fetchStockRange.mockResolvedValue({ days: [{ day: '2026-10-21' }] })
  store = useLabMonitoringStore()
})

describe('opening the sandbox', () => {
  it('shows the first pinned SKU, as the real page would', async () => {
    await store.init()

    expect(store.selectedId).toBe(PINNED.nm_id)
    expect(store.product).toEqual({ nm_id: PINNED.nm_id })
    expect(store.stockDays).toEqual([{ day: '2026-10-21' }])
  })

  it('falls back to the first listed SKU when nothing is pinned', async () => {
    fetchPinnedSkus.mockResolvedValue({ items: [] })

    await store.init()

    expect(store.selectedId).toBe(LISTED.nm_id)
  })

  it('loads the same SKU over a year for the long chart', async () => {
    await store.init()

    const [windowCall, yearCall] = fetchSkuDetail.mock.calls.map(([, params]) => params)
    expect(windowCall).toEqual({ date_from: store.dateFrom, date_to: store.dateTo })
    expect(yearCall.date_to).toBe(store.dateTo)
    expect(yearCall.date_from < store.dateFrom).toBe(true)
    expect(store.longProduct).toEqual({ nm_id: PINNED.nm_id })
  })
})

describe('a failed load', () => {
  it('is a message, and no SKU is requested without a catalogue', async () => {
    fetchSkuSummary.mockRejectedValue(new Error('Сеть недоступна'))

    await store.init()

    expect(store.error).toBeTruthy()
    expect(fetchSkuDetail).not.toHaveBeenCalled()
  })
})
