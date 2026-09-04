/**
 * How the P&L period is remembered between visits.
 *
 * Kept out of `store.spec.js` because the rules here are about time and storage
 * rather than about fetching: a saved period expires, and a saved period that
 * meant «последняя неделя» has to find the weeks harvested since. The last two
 * cases go through the store, since being remembered correctly and never being
 * read on load would look identical from inside this module.
 */
import { createPinia, setActivePinia } from 'pinia'

import { fetchCostPrices, fetchSkuPnl, fetchWeeks } from '@/modules/finreports/api'
import {
  readSavedPeriod,
  restoreSavedPeriod,
  shiftIsoDate,
  spanDays,
  writeSavedPeriod,
} from '@/modules/finreports/savedPeriod'
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

const KEY = 'finreports:period'

/** The harvested history as `fullSpan` reports it. */
const SPAN = { date_from: '2024-01-29', date_to: '2026-07-19' }
/** The same history after the hourly harvest brought the next week. */
const SPAN_PLUS_A_WEEK = { date_from: '2024-01-29', date_to: '2026-07-26' }

const WEEKS = [
  { report_id: 969371534, date_from: '2026-07-13', date_to: '2026-07-19' },
  { report_id: 785000000, date_from: '2026-07-06', date_to: '2026-07-12' },
  { report_id: 912732521, date_from: '2024-01-29', date_to: '2024-02-04' },
]
const NEWER_WEEKS = [{ report_id: 786, date_from: '2026-07-20', date_to: '2026-07-26' }, ...WEEKS]

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.clearAllMocks()
  fetchWeeks.mockResolvedValue({ weeks: WEEKS })
  fetchSkuPnl.mockResolvedValue({ rows: [], notes: [] })
  fetchCostPrices.mockResolvedValue({ currency: 'KGS', items: [], missing: [] })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('calendar arithmetic', () => {
  it('shifts a day without falling into the timezone behind UTC', () => {
    // `new Date('2026-07-19')` is UTC midnight; formatting it in a calendar
    // behind UTC gives the 18th. These are calendar days, so the maths is UTC.
    expect(shiftIsoDate('2026-07-19', -6)).toBe('2026-07-13')
    expect(shiftIsoDate('2026-07-19', 0)).toBe('2026-07-19')
    expect(shiftIsoDate('2026-02-28', 2)).toBe('2026-03-02')
  })

  it('counts a window with both ends inside it', () => {
    expect(spanDays('2026-07-13', '2026-07-19')).toBe(7)
    expect(spanDays('2026-07-19', '2026-07-19')).toBe(1)
  })
})

describe('how long a chosen period lasts', () => {
  it('gives back a period chosen within the day', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-19T08:00:00Z'))
    writeSavedPeriod('2024-02-01', '2024-02-04', SPAN)

    vi.setSystemTime(new Date('2026-07-19T21:00:00Z'))

    expect(readSavedPeriod()).toMatchObject({ from: '2024-02-01', to: '2024-02-04' })
  })

  it('forgets one chosen more than a day ago, and clears it away', () => {
    // The behaviour this replaces: a window picked once stayed pinned for as
    // long as the browser remembered it, hiding every report published since.
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-19T08:00:00Z'))
    writeSavedPeriod('2024-02-01', '2024-02-04', SPAN)

    vi.setSystemTime(new Date('2026-07-20T09:00:00Z')) // 25 hours later

    expect(readSavedPeriod()).toBeNull()
    expect(localStorage.getItem(KEY)).toBeNull()
  })

  it('drops an entry saved before periods expired at all', () => {
    // No stamp = written by the build that pinned the period indefinitely. That
    // entry IS the stale pin, so it is dropped rather than grandfathered in.
    localStorage.setItem(KEY, JSON.stringify({ from: '2024-02-01', to: '2024-02-04' }))

    expect(readSavedPeriod()).toBeNull()
  })

  it('ignores a half-written or unreadable entry instead of throwing', () => {
    localStorage.setItem(KEY, '{"from":"2024-02-01"}')
    expect(readSavedPeriod()).toBeNull()

    localStorage.setItem(KEY, 'not json')
    expect(readSavedPeriod()).toBeNull()
  })
})

describe('where a remembered period lands', () => {
  /** A period chosen `to`-`from`, against the history as it stood at `span`. */
  function saved(from, to, span = SPAN) {
    writeSavedPeriod(from, to, span)
    return readSavedPeriod()
  }

  it('slides a window that ended on the then-newest day, keeping its length', () => {
    const landed = restoreSavedPeriod(saved('2026-07-13', '2026-07-19'), SPAN_PLUS_A_WEEK)

    expect(landed).toEqual({ from: '2026-07-20', to: '2026-07-26' })
  })

  it('extends «вся история» instead of sliding it', () => {
    // Anchored at both ends: preserving its LENGTH would walk the start forward
    // and quietly drop the oldest days out of the total.
    const landed = restoreSavedPeriod(saved('2024-01-29', '2026-07-19'), SPAN_PLUS_A_WEEK)

    expect(landed).toEqual({ from: '2024-01-29', to: '2026-07-26' })
  })

  it('leaves a window that stopped short of the newest day exactly where it was', () => {
    const landed = restoreSavedPeriod(saved('2024-01-29', '2024-02-04'), SPAN_PLUS_A_WEEK)

    expect(landed).toEqual({ from: '2024-01-29', to: '2024-02-04' })
  })

  it('leaves the latest window alone when no new week arrived', () => {
    const landed = restoreSavedPeriod(saved('2026-07-13', '2026-07-19'), SPAN)

    expect(landed).toEqual({ from: '2026-07-13', to: '2026-07-19' })
  })

  it('writes down where a followed window landed, without renewing its day', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-19T08:00:00Z'))
    const chosen = saved('2026-07-13', '2026-07-19')

    vi.setSystemTime(new Date('2026-07-19T20:00:00Z'))
    restoreSavedPeriod(chosen, SPAN_PLUS_A_WEEK)

    expect(readSavedPeriod()).toMatchObject({ from: '2026-07-20', to: '2026-07-26' })
    // Following the data is not a fresh choice: the day still runs from 08:00.
    vi.setSystemTime(new Date('2026-07-20T09:00:00Z'))
    expect(readSavedPeriod()).toBeNull()
  })
})

describe('what the P&L page shows on load', () => {
  /** A page reload: the store is gone, only localStorage survives. */
  async function reload(weeks = WEEKS) {
    setActivePinia(createPinia())
    const store = useFinReportsStore()
    fetchWeeks.mockResolvedValue({ weeks })
    await store.loadWeeks()
    return store
  }

  it('follows the harvest instead of reopening on the week it was left on', async () => {
    const store = await reload()
    store.setPresetDays(7) // «последняя неделя» — ends on the newest settled day

    const reopened = await reload(NEWER_WEEKS)

    expect(reopened.dateFrom).toBe('2026-07-20')
    expect(reopened.dateTo).toBe('2026-07-26')
  })

  it('falls back to the last settled week once the saved period has expired', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-19T08:00:00Z'))
    const store = await reload()
    store.setPeriod('2024-02-01', '2024-02-04')

    vi.setSystemTime(new Date('2026-07-20T09:00:00Z'))
    const reopened = await reload()

    expect(reopened.dateFrom).toBe('2026-07-13')
    expect(reopened.dateTo).toBe('2026-07-19')
  })
})
