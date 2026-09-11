import { createPinia, setActivePinia } from 'pinia'

import {
  deleteCostPrice,
  downloadCostPricesXlsx,
  fetchBalance,
  fetchCostPrices,
  fetchHarvestState,
  fetchSkuPnl,
  fetchWeeks,
  importCostPricesXlsx,
  saveCostPrices,
  setBalancePin,
  setSkuExclusion,
  triggerHarvest,
} from '@/modules/finreports/api'
import { writePendingRefresh } from '@/modules/finreports/pendingRefresh'
import { useFinReportsStore } from '@/modules/finreports/store'

vi.mock('@/modules/finreports/api', () => ({
  deleteCostPrice: vi.fn(),
  downloadCostPricesXlsx: vi.fn(),
  fetchBalance: vi.fn(),
  fetchCostPrices: vi.fn(),
  fetchHarvestState: vi.fn(),
  fetchSkuPnl: vi.fn(),
  fetchWeeks: vi.fn(),
  importCostPricesXlsx: vi.fn(),
  saveCostPrices: vi.fn(),
  setBalancePin: vi.fn(),
  setSkuExclusion: vi.fn(),
  triggerHarvest: vi.fn(),
}))

const WEEKS = [
  { report_id: 969371534, date_from: '2026-07-13', date_to: '2026-07-19' },
  { report_id: 785000000, date_from: '2026-07-06', date_to: '2026-07-12' },
  { report_id: 912732521, date_from: '2024-01-29', date_to: '2024-02-04' },
]

const REPORT = { totals: { payout_net: '2010193.84' }, rows: [], unallocated: null, notes: [] }

let store

/**
 * A store as a fresh page load sees it — new Pinia, nothing in memory, and
 * whatever the browser wrote down still in `localStorage`. This is the whole
 * subject of the reload tests, so it has to be a real second store rather than
 * the same one with its refs poked.
 */
function freshStore() {
  setActivePinia(createPinia())
  return useFinReportsStore()
}

/** A click older than the poll ever waits, so its note no longer counts. */
const OLD_CLICK = new Date(Date.now() - 21 * 60 * 1000).toISOString()

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

describe('cost-price Excel round trip', () => {
  it('returns the exported blob and filename for the view to download', async () => {
    const blob = new Blob(['xlsx'])
    downloadCostPricesXlsx.mockResolvedValue({ blob, filename: 'себестоимость.xlsx' })

    const result = await store.exportCostPrices()

    expect(result).toEqual({ blob, filename: 'себестоимость.xlsx' })
  })

  it('drops the cached report and reloads costs after an import', async () => {
    // An applied cost restates every margin, exactly like a manual save.
    await store.loadWeeks()
    await store.loadReport()
    importCostPricesXlsx.mockResolvedValue({ applied: 3, skipped: 1, issues: [] })

    const summary = await store.importCostPrices(new File(['x'], 'costs.xlsx'))

    expect(summary.applied).toBe(3)
    expect(store.report).toBeNull()
    expect(fetchCostPrices).toHaveBeenCalled()
  })

  it('surfaces a rejected import and rethrows without touching the report', async () => {
    await store.loadWeeks()
    await store.loadReport()
    importCostPricesXlsx.mockRejectedValue({ response: { data: { detail: 'Файл пуст.' } } })

    await expect(store.importCostPrices(new File([''], 'x.xlsx'))).rejects.toBeDefined()
    expect(store.costsError).toBe('Файл пуст.')
    expect(store.report).toEqual(REPORT)
    expect(store.costsSaving).toBe(false)
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

describe('balance marks', () => {
  /**
   * A mark is applied to the loaded payload first and persisted after, so the
   * grid re-orders on the click rather than a round trip. That makes the SHAPE
   * of what is written load-bearing: the grid matches a mark against the row's
   * own `nm_id`, a number, so a SKU mark stored as text applies to nothing and
   * the click looks ignored until the next reload.
   */
  const PAYLOAD = {
    stat_date: '2026-08-03',
    rows: [],
    uncounted_warehouses: [],
    uncounted_skus: [],
  }

  beforeEach(async () => {
    fetchBalance.mockResolvedValue({ ...PAYLOAD })
    await store.loadBalance()
    vi.clearAllMocks()
  })

  it('applies a SKU mark as a number, without refetching', async () => {
    await store.toggleBalancePin('sku_uncounted', '953770957', true)

    expect(store.balance.uncounted_skus).toEqual([953770957])
    expect(setBalancePin).toHaveBeenCalledWith('sku_uncounted', '953770957', true)
    expect(fetchBalance).not.toHaveBeenCalled()
  })

  it('applies a warehouse mark as its name', async () => {
    await store.toggleBalancePin('warehouse_uncounted', 'Тула', true)

    expect(store.balance.uncounted_warehouses).toEqual(['Тула'])
  })

  it('rolls a failed mark back and says so', async () => {
    setBalancePin.mockRejectedValueOnce({ response: { data: { detail: 'Не сохранено' } } })

    await store.toggleBalancePin('sku_uncounted', '953770957', true)

    expect(store.balance.uncounted_skus).toEqual([])
    expect(store.balanceError).toBe('Не сохранено')
  })
})

describe('«Обновить» — the manual WB harvest', () => {
  /**
   * The poll waits real milliseconds between attempts, so the clock is faked.
   * `runAllTimersAsync` drives it: each awaited timer resolves and the loop
   * takes its next turn, without the suite waiting five seconds per attempt.
   */
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  /** Run `action` to completion while advancing the fake clock. */
  async function settle(action) {
    const running = action()
    await vi.runAllTimersAsync()
    await running
  }

  it('answers a rate-limited click at once and enqueues nothing', async () => {
    // The case the whole refactor is for. WB meters the settlement report at
    // one request per ~15 minutes, so a click inside that window used to
    // enqueue a harvest whose first act was to sit still for most of it —
    // seven minutes of «Обновляем…» over a walk doing nothing (prod
    // 2026-09-09). There is no version of waiting that helps, so the page says
    // when to come back and stops.
    triggerHarvest.mockResolvedValue({
      status: 'rate_limited',
      task_id: null,
      retry_after_seconds: 391,
    })

    await store.refreshFromWb()

    expect(store.harvestBusy).toBe(false)
    expect(store.harvestNotice).toBe(
      'Ограничение по запросам от Wildberries — попробуйте через 7 мин.',
    )
    expect(fetchHarvestState).not.toHaveBeenCalled()
    expect(localStorage.getItem('finreports:pending-refresh')).toBeNull()
  })

  it('never tells a seller to come back in zero minutes', async () => {
    // A click inside WB's window restarts it, so «через 0 минут» would invite
    // exactly the mistake the message exists to prevent.
    triggerHarvest.mockResolvedValue({
      status: 'rate_limited',
      task_id: null,
      retry_after_seconds: 4,
    })

    await store.refreshFromWb()

    expect(store.harvestNotice).toContain('1 мин')
  })

  it('gives the button back as soon as the trigger answers', async () => {
    // No timers advanced: the click resolves in one round trip. It used to be
    // awaited for the length of the harvest, which is what made a slow WB read
    // as a broken page.
    triggerHarvest.mockResolvedValue({ status: 'started', task_id: 'task-1' })
    fetchHarvestState.mockResolvedValue({ running: true, latest_settled: '2026-07-19' })

    await store.refreshFromWb()

    expect(store.harvestBusy).toBe(false)
    expect(store.harvestNotice).toContain('идёт в фоне')
  })

  it('keeps watching in the background after the click has answered', async () => {
    // The click is over, but the statement still refreshes itself when the week
    // lands — that is what makes "no waiting" honest rather than a shrug.
    await store.loadWeeks()
    triggerHarvest.mockResolvedValue({ status: 'started', task_id: 'task-1' })
    fetchHarvestState
      .mockResolvedValueOnce({ running: true, latest_settled: '2026-07-19' })
      .mockResolvedValue({ running: false, latest_settled: '2026-07-26' })
    fetchWeeks.mockResolvedValue({
      weeks: [{ report_id: 786, date_from: '2026-07-20', date_to: '2026-07-26' }, ...WEEKS],
    })

    await store.refreshFromWb()
    await vi.runAllTimersAsync()

    expect(store.harvestNotice).toContain('2026-07-26')
    expect(store.dateTo).toBe('2026-07-26')
  })

  it('reports a new week and reloads the statement when one arrives', async () => {
    await store.loadWeeks()
    triggerHarvest.mockResolvedValue({ status: 'started', task_id: 'task-1' })
    fetchHarvestState
      .mockResolvedValueOnce({ running: true, latest_settled: '2026-07-19' })
      .mockResolvedValue({ running: false, latest_settled: '2026-07-26' })
    fetchWeeks.mockResolvedValue({
      weeks: [{ report_id: 786, date_from: '2026-07-20', date_to: '2026-07-26' }, ...WEEKS],
    })

    await settle(() => store.refreshFromWb())

    expect(store.harvestBusy).toBe(false)
    expect(store.harvestNotice).toContain('2026-07-26')
    expect(store.dateTo).toBe('2026-07-26')
  })

  it('says so plainly when WB had nothing new', async () => {
    await store.loadWeeks()
    triggerHarvest.mockResolvedValue({ status: 'started', task_id: 'task-1' })
    fetchHarvestState.mockResolvedValue({ running: false, latest_settled: '2026-07-19' })

    await settle(() => store.refreshFromWb())

    expect(store.harvestNotice).toBe('Новых отчётов у Wildberries пока нет.')
    expect(store.dateTo).toBe('2026-07-19')
  })

  it('waits out a harvest that was already running instead of starting another', async () => {
    await store.loadWeeks()
    triggerHarvest.mockResolvedValue({ status: 'already_running', task_id: null })
    fetchHarvestState.mockResolvedValue({ running: false, latest_settled: '2026-07-19' })

    await settle(() => store.refreshFromWb())

    expect(triggerHarvest).toHaveBeenCalledTimes(1)
    expect(fetchHarvestState).toHaveBeenCalled()
  })

  it('measures a resumed run against the day of the click, not of the reload', async () => {
    // The comparison that decides «Загружен отчёт по …» vs «новых отчётов нет»
    // is against the moment of the CLICK. A reload has forgotten that moment,
    // and by then the history may already have moved — comparing the new day
    // against itself reports a week that did arrive as nothing new. The note
    // is what carries the baseline across.
    writePendingRefresh('task-1', '2026-07-19')
    fetchHarvestState
      .mockResolvedValueOnce({ running: true, latest_settled: '2026-07-26' })
      .mockResolvedValue({ running: false, latest_settled: '2026-07-26' })
    fetchWeeks.mockResolvedValue({
      weeks: [{ report_id: 786, date_from: '2026-07-20', date_to: '2026-07-26' }, ...WEEKS],
    })

    await settle(() => store.loadHarvestState())

    expect(store.harvestNotice).toContain('2026-07-26')
  })

  it('reports how a refresh ended when it finished while the tab was away', async () => {
    // The other end of the same gap: nothing holds the lock after the task
    // finishes either, so a reload a minute later found `running: false` and
    // said nothing at all — the click just vanished. The note carries the day
    // the click was measured against, so the answer is still computable.
    writePendingRefresh('task-1', '2026-07-19')
    fetchHarvestState.mockResolvedValue({ running: false, latest_settled: '2026-07-26' })
    fetchWeeks.mockResolvedValue({
      weeks: [{ report_id: 786, date_from: '2026-07-20', date_to: '2026-07-26' }, ...WEEKS],
    })

    await store.loadHarvestState()

    expect(store.harvestBusy).toBe(false)
    expect(store.harvestNotice).toContain('2026-07-26')
  })

  it('does not resurrect a refresh once it has been resolved', async () => {
    // The note is cleared at the ending, so the next reload is an ordinary
    // page load. Left behind, it would re-announce the same result on every
    // visit for the rest of its lifetime.
    await store.loadWeeks()
    triggerHarvest.mockResolvedValue({ status: 'started', task_id: 'task-1' })
    fetchHarvestState.mockResolvedValue({ running: false, latest_settled: '2026-07-19' })
    await settle(() => store.refreshFromWb())

    const reloaded = freshStore()
    await reloaded.loadHarvestState()

    expect(reloaded.harvestNotice).toBe('')
  })

  it('gives the button back when the note is older than the poll ever waits', async () => {
    // A worker killed mid-task holds no lock and finishes nothing. A note with
    // no expiry would disable «Обновить» for good — a worse failure than the
    // one it exists to fix.
    localStorage.setItem(
      'finreports:pending-refresh',
      JSON.stringify({ task_id: 'task-1', settled_before: '2026-07-19', asked_at: OLD_CLICK }),
    )
    fetchHarvestState.mockResolvedValue({ running: false, latest_settled: '2026-07-19' })

    await store.loadHarvestState()

    expect(store.harvestNotice).toBe('')
  })

  it('comes back to a running harvest after a page reload', async () => {
    // The state that matters here is the SERVER's, not the click's. It lived
    // only in the store, so reloading mid-run put «Обновить» back on an
    // enabled button over a harvest that was still going — clicking it again
    // did nothing, and the seller had no way to tell whether their refresh was
    // still happening.
    fetchHarvestState.mockResolvedValue({
      running: true,
      latest_settled: '2026-07-19',
      latest_report: null,
      last_check: null,
    })

    await store.loadHarvestState()

    expect(store.harvestNotice).toContain('Обновление уже идёт')
  })

  it('resolves a resumed harvest the same way a clicked one resolves', async () => {
    fetchHarvestState
      .mockResolvedValueOnce({ running: true, latest_settled: '2026-07-19' })
      .mockResolvedValue({ running: false, latest_settled: '2026-07-19' })

    await settle(() => store.loadHarvestState())

    expect(store.harvestNotice).toBe('Новых отчётов у Wildberries пока нет.')
  })

  it('does not announce a new week for a run it only joined halfway', async () => {
    // The baseline is the settlement day the resumed state itself carries. It
    // used to be the store's own span, which is still empty this early in a
    // page load — and every non-empty day differs from an empty string, so a
    // run that brought nothing would be announced as «Загружен отчёт по …».
    fetchHarvestState
      .mockResolvedValueOnce({ running: true, latest_settled: '2026-07-19' })
      .mockResolvedValue({ running: false, latest_settled: '2026-07-19' })

    await settle(() => store.loadHarvestState())

    expect(store.harvestNotice).not.toContain('Загружен')
    expect(fetchWeeks).not.toHaveBeenCalled()
  })

  it('does not start a second poll loop for a harvest it is already watching', async () => {
    // Two loops over one harvest fire `onNewReports` twice for one arrival —
    // two statement reloads, and the period jumping forward twice.
    triggerHarvest.mockResolvedValue({ status: 'started', task_id: 'task-1' })
    fetchHarvestState.mockResolvedValue({ running: false, latest_settled: '2026-07-19' })

    const clicked = store.refreshFromWb()
    await store.loadHarvestState()
    await vi.runAllTimersAsync()
    await clicked

    expect(triggerHarvest).toHaveBeenCalledTimes(1)
    expect(fetchWeeks).not.toHaveBeenCalled()
  })

  it('ignores a second click while one refresh is still in flight', async () => {
    await store.loadWeeks()
    triggerHarvest.mockResolvedValue({ status: 'started', task_id: 'task-1' })
    fetchHarvestState.mockResolvedValue({ running: false, latest_settled: '2026-07-19' })

    const first = store.refreshFromWb()
    const second = store.refreshFromWb()
    await vi.runAllTimersAsync()
    await Promise.all([first, second])

    expect(triggerHarvest).toHaveBeenCalledTimes(1)
  })

  it('keeps a deliberately chosen older period when a new week lands', async () => {
    await store.loadWeeks()
    store.setPeriod('2024-01-29', '2024-02-04')
    triggerHarvest.mockResolvedValue({ status: 'started', task_id: 'task-1' })
    fetchHarvestState.mockResolvedValue({ running: false, latest_settled: '2026-07-26' })
    fetchWeeks.mockResolvedValue({
      weeks: [{ report_id: 786, date_from: '2026-07-20', date_to: '2026-07-26' }, ...WEEKS],
    })

    await settle(() => store.refreshFromWb())

    expect(store.dateFrom).toBe('2024-01-29')
    expect(store.dateTo).toBe('2024-02-04')
  })

  it('surfaces a failed trigger instead of pretending a harvest started', async () => {
    triggerHarvest.mockRejectedValue(new Error('нет связи'))

    await settle(() => store.refreshFromWb())

    expect(store.harvestBusy).toBe(false)
    expect(store.harvestError).toBeTruthy()
    expect(fetchHarvestState).not.toHaveBeenCalled()
  })

  it('keeps watching when a single status poll fails', async () => {
    await store.loadWeeks()
    triggerHarvest.mockResolvedValue({ status: 'started', task_id: 'task-1' })
    fetchHarvestState
      .mockRejectedValueOnce(new Error('таймаут'))
      .mockResolvedValue({ running: false, latest_settled: '2026-07-19' })

    await settle(() => store.refreshFromWb())

    expect(store.harvestError).toBe('')
    expect(store.harvestNotice).toBe('Новых отчётов у Wildberries пока нет.')
  })
})

describe('«Обновить» — how the period follows new data', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    triggerHarvest.mockResolvedValue({ status: 'started', task_id: 'task-1' })
    fetchHarvestState.mockResolvedValue({ running: false, latest_settled: '2026-07-26' })
    fetchWeeks.mockResolvedValue({
      weeks: [{ report_id: 786, date_from: '2026-07-20', date_to: '2026-07-26' }, ...WEEKS],
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  async function refresh() {
    const running = store.refreshFromWb()
    await vi.runAllTimersAsync()
    await running
  }

  it('extends «вся история» instead of sliding it forward', async () => {
    fetchWeeks.mockResolvedValueOnce({ weeks: WEEKS })
    await store.loadWeeks()
    store.setPresetAll()
    const oldestDay = store.dateFrom

    await refresh()

    expect(store.dateFrom).toBe(oldestDay)
    expect(store.dateTo).toBe('2026-07-26')
  })

  it('slides a last-N-days window forward, keeping its length', async () => {
    fetchWeeks.mockResolvedValueOnce({ weeks: WEEKS })
    await store.loadWeeks()
    store.setPresetDays(30)

    await refresh()

    expect(store.dateTo).toBe('2026-07-26')
    expect(store.dateFrom).toBe('2026-06-27')
  })
})
