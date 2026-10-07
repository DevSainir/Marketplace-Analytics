/**
 * The window the summary opens on.
 *
 * It has to be exactly the window the calendar's «7 дней» stands for: the
 * presets live in the calendar now, and a default built by other arithmetic
 * opens the page with no preset lit — the summary computed its own through
 * `toISOString` once, a day early east of Greenwich.
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { presetRange } from '@/core/utils/calendarModel'
import { fetchSummary, fetchSummarySpan } from '@/modules/summary/api'
import { useSummaryStore } from '@/modules/summary/store'

vi.mock('@/modules/summary/api', () => ({
  fetchSummary: vi.fn(),
  fetchSummarySpan: vi.fn(),
}))

const SPAN = { date_from: '2024-07-11', date_to: '2026-09-16', settled_to: '2026-09-13' }

let store

beforeEach(async () => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.clearAllMocks()
  fetchSummarySpan.mockResolvedValue(SPAN)
  fetchSummary.mockResolvedValue({ kpi: null, days: [], rows: [], currency: 'KGS' })
  store = useSummaryStore()
  await store.init()
})

describe('the period on load', () => {
  it("opens on the calendar's «7 дней» ending on the newest settled day", async () => {
    expect(store.dateTo).toBe(SPAN.date_to)
    expect({ from: store.dateFrom, to: store.dateTo }).toEqual(presetRange(7, SPAN.date_to))
  })

  it('reopens on the window chosen within the hour', async () => {
    // A detour to another page or a reload must not throw the choice away.
    await store.setPeriod('2026-08-01', '2026-08-31')

    setActivePinia(createPinia())
    const reopened = useSummaryStore()
    await reopened.init()

    expect({ from: reopened.dateFrom, to: reopened.dateTo }).toEqual({
      from: '2026-08-01',
      to: '2026-08-31',
    })
  })
})
