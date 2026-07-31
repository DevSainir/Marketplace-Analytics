import { createPinia, setActivePinia } from 'pinia'

import {
  deleteCostPrice,
  fetchCostPrices,
  fetchSkuPnl,
  fetchWeeks,
  saveCostPrices,
  setSkuExclusion,
} from '@/modules/finreports/api'
import { useFinReportsStore } from '@/modules/finreports/store'

vi.mock('@/modules/finreports/api', () => ({
  deleteCostPrice: vi.fn(),
  fetchCostPrices: vi.fn(),
  fetchSkuPnl: vi.fn(),
  fetchWeeks: vi.fn(),
  saveCostPrices: vi.fn(),
  setSkuExclusion: vi.fn(),
}))

const WEEKS = [
  { report_id: 969371534, date_from: '2026-07-13', date_to: '2026-07-19' },
  { report_id: 785000000, date_from: '2026-07-06', date_to: '2026-07-12' },
  { report_id: 912732521, date_from: '2024-01-29', date_to: '2024-02-04' },
]

const REPORT = { totals: { payout_net: '2010193.84' }, rows: [], unallocated: null, notes: [] }

let store

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  store = useFinReportsStore()
  vi.clearAllMocks()
  fetchWeeks.mockResolvedValue({ weeks: WEEKS })
  fetchSkuPnl.mockResolvedValue(REPORT)
  fetchCostPrices.mockResolvedValue({ currency: 'KGS', items: [], missing: [] })
})

describe('period selection', () => {
  it('spans the whole harvested history in fullSpan', async () => {
    await store.loadWeeks()

    // The list arrives newest-first, so a naive first/last read gets it backwards.
    expect(store.fullSpan).toEqual({ date_from: '2024-01-29', date_to: '2026-07-19' })
  })

  it('defaults to the last week, anchored to the newest harvested day', async () => {
    // NOT the whole history: the recent window is what a seller checks daily,
    // and it renders an order of magnitude faster than 2.5 years of rows.
    await store.loadWeeks()

    expect(store.dateTo).toBe('2026-07-19')
    expect(store.dateFrom).toBe('2026-07-13') // 7 days inclusive
  })

  it('restores the last chosen period on reload instead of the default', async () => {
    await store.loadWeeks()
    store.setPeriod('2025-03-04', '2025-11-17')

    // A page reload resets the store; a fresh one must read the saved period.
    setActivePinia(createPinia())
    const reloaded = useFinReportsStore()
    fetchWeeks.mockResolvedValue({ weeks: WEEKS })
    await reloaded.loadWeeks()

    expect(reloaded.dateFrom).toBe('2025-03-04')
    expect(reloaded.dateTo).toBe('2025-11-17')
  })

  it('accepts an arbitrary start/end pair, not only report weeks', async () => {
    store.setPeriod('2025-03-04', '2025-11-17')
    await store.loadReport()

    expect(fetchSkuPnl).toHaveBeenCalledWith(
      { date_from: '2025-03-04', date_to: '2025-11-17' },
      expect.any(AbortSignal),
    )
  })

  it('corrects a reversed range instead of rejecting it', () => {
    store.setPeriod('2026-07-19', '2026-07-01')

    expect(store.dateFrom).toBe('2026-07-01')
    expect(store.dateTo).toBe('2026-07-19')
  })

  it('anchors day presets to the newest harvested day, not today', async () => {
    // «Последние 7 дней» against the calendar would often be an empty window:
    // WB settles with a lag, so the newest data can be days old.
    await store.loadWeeks()

    store.setPresetDays(7)

    expect(store.dateTo).toBe('2026-07-19')
    expect(store.dateFrom).toBe('2026-07-13')
  })

  it('the «вся история» preset selects the full harvested span', async () => {
    await store.loadWeeks()

    store.setPresetAll()

    expect(store.dateFrom).toBe('2024-01-29')
    expect(store.dateTo).toBe('2026-07-19')
  })

  it('does not fetch before a period is chosen', async () => {
    await store.loadReport()

    expect(fetchSkuPnl).not.toHaveBeenCalled()
  })
})

describe('overlapping requests', () => {
  it('lets the newest request win when the period changes twice quickly', async () => {
    // A whole-history request takes seconds over 620k rows, so two period
    // changes genuinely overlap. A slow response for the old period landing
    // after the new one would leave figures on screen for a period the picker
    // no longer names.
    await store.loadWeeks()
    let releaseFirst
    fetchSkuPnl.mockImplementationOnce(
      () => new Promise((resolve) => (releaseFirst = () => resolve({ totals: { key: 'stale' } }))),
    )
    fetchSkuPnl.mockResolvedValueOnce({ totals: { key: 'fresh' } })

    const first = store.loadReport()
    const second = store.loadReport()
    releaseFirst()
    await Promise.all([first, second])

    expect(store.report.totals.key).toBe('fresh')
  })

  it('aborts the superseded request instead of leaving it in flight', async () => {
    await store.loadWeeks()
    fetchSkuPnl.mockImplementation(() => new Promise(() => {}))

    store.loadReport()
    const firstSignal = fetchSkuPnl.mock.calls[0][1]
    store.loadReport()

    expect(firstSignal.aborted).toBe(true)
  })
})

describe('cost prices invalidating the report', () => {
  it('drops the cached report after a save', async () => {
    // A saved cost restates every margin already on screen. Keeping the old
    // report next to the new cost shows a profit the seller might act on.
    await store.loadWeeks()
    await store.loadReport()
    saveCostPrices.mockResolvedValue({ saved: 1 })

    await store.persistCostPrices([{ nm_id: 953770957, cost: 662 }])

    expect(store.report).toBeNull()
  })

  it('drops the cached report after a cost is cleared', async () => {
    await store.loadWeeks()
    await store.loadReport()
    deleteCostPrice.mockResolvedValue(undefined)

    await store.removeCostPrice(953770957)

    expect(store.report).toBeNull()
  })

  it('reloads the cost list after a save so the grid matches the server', async () => {
    saveCostPrices.mockResolvedValue({ saved: 1 })

    await store.persistCostPrices([{ nm_id: 953770957, cost: 662 }])

    expect(fetchCostPrices).toHaveBeenCalled()
  })

  it('surfaces a rejected save and rethrows so the view can react', async () => {
    saveCostPrices.mockRejectedValue({ response: { data: { detail: 'Себестоимость неверна' } } })

    await expect(store.persistCostPrices([{ nm_id: 1, cost: -1 }])).rejects.toBeDefined()
    expect(store.costsError).toBe('Себестоимость неверна')
    expect(store.costsSaving).toBe(false)
  })

  it('keeps the report when the save failed', async () => {
    // Nothing changed on the server, so the report on screen is still true.
    await store.loadWeeks()
    await store.loadReport()
    saveCostPrices.mockRejectedValue(new Error('network'))

    await expect(store.persistCostPrices([{ nm_id: 1, cost: 1 }])).rejects.toThrow()
    expect(store.report).toEqual(REPORT)
  })
})

describe('excluding a SKU from the общий счёт', () => {
  it('persists the mark then reloads so the backend recomputes the dashboard', async () => {
    await store.loadWeeks()
    await store.loadReport()
    setSkuExclusion.mockResolvedValue(undefined)
    fetchSkuPnl.mockClear()

    await store.toggleExclusion(953770957, true)

    expect(setSkuExclusion).toHaveBeenCalledWith(953770957, true)
    // The dashboard is the backend's, so the store re-fetches rather than
    // adjusting totals on the client.
    expect(fetchSkuPnl).toHaveBeenCalled()
  })

  it('flips the row optimistically before the reload lands', async () => {
    await store.loadWeeks()
    store.report = { rows: [{ nm_id: 1, is_excluded: false }], dashboard: {} }
    setSkuExclusion.mockResolvedValue(undefined)
    // Freeze the reload so we can observe the optimistic state.
    fetchSkuPnl.mockImplementation(() => new Promise(() => {}))

    store.toggleExclusion(1, true)

    expect(store.report.rows[0].is_excluded).toBe(true)
  })

  it('surfaces a failed mark and still reloads to resync', async () => {
    await store.loadWeeks()
    await store.loadReport()
    setSkuExclusion.mockRejectedValue({ response: { data: { detail: 'Нельзя' } } })
    fetchSkuPnl.mockClear()

    await store.toggleExclusion(1, true)

    expect(store.reportError).toBe('Нельзя')
    expect(fetchSkuPnl).toHaveBeenCalled()
  })
})

describe('failures', () => {
  it('records a report error instead of throwing at the view', async () => {
    await store.loadWeeks()
    fetchSkuPnl.mockRejectedValue({ response: { data: { detail: 'Отчёт недоступен' } } })

    await store.loadReport()

    expect(store.reportError).toBe('Отчёт недоступен')
    expect(store.reportLoading).toBe(false)
  })

  it('clears a previous error on a successful reload', async () => {
    await store.loadWeeks()
    fetchSkuPnl.mockRejectedValueOnce(new Error('boom'))
    await store.loadReport()

    fetchSkuPnl.mockResolvedValue(REPORT)
    await store.loadReport()

    expect(store.reportError).toBe('')
    expect(store.report).toEqual(REPORT)
  })
})
