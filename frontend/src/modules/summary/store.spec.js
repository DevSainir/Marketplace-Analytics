/**
 * The window the store sets, against the window the controls test for.
 *
 * These are two places that have to agree on one arithmetic — «7 дней ending on
 * the newest day» — and they disagreed for a while: one used the local
 * calendar, the other went through `toISOString`, which converts to UTC. East
 * of Greenwich that is a day earlier, so every preset set a window and then
 * failed to recognise it, and no quick period was ever highlighted.
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
  setActivePinia(createPinia())
  vi.clearAllMocks()
  fetchSummarySpan.mockResolvedValue(SPAN)
  fetchSummary.mockResolvedValue({ kpi: null, days: [], rows: [], currency: 'KGS' })
  store = useSummaryStore()
  await store.init()
})

describe('the period presets', () => {
  it('opens on a week ending on the newest day any feed has', async () => {
    expect(store.dateTo).toBe(SPAN.date_to)
    expect({ from: store.dateFrom, to: store.dateTo }).toEqual(presetRange(7, SPAN.date_to))
  })

  it('sets exactly the window the controls recognise', async () => {
    for (const days of [7, 30, 90]) {
      await store.setPresetDays(days)

      expect({ from: store.dateFrom, to: store.dateTo }).toEqual(presetRange(days, SPAN.date_to))
    }
  })

  it('covers the whole span on «Вся история»', async () => {
    await store.setPresetAll()

    expect(store.dateFrom).toBe(SPAN.date_from)
    expect(store.isAllHistory).toBe(true)
  })
})
