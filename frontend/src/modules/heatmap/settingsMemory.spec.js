/**
 * The heatmap remembers its settings for twenty minutes after the last change,
 * per кабинет, and starts on its defaults when storage has nothing fresh.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setWorkspaceId } from '@/core/api/axios'
import { recallSettings, rememberSettings } from '@/modules/heatmap/settingsMemory'

describe('settings memory', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.useFakeTimers()
    setWorkspaceId('ws-1')
  })

  afterEach(() => vi.useRealTimers())

  it('gives back what was remembered within twenty minutes', () => {
    rememberSettings({ metric: 'profit' })
    vi.advanceTimersByTime(19 * 60 * 1000)

    expect(recallSettings()).toEqual({ metric: 'profit' })
  })

  it('forgets the settings twenty minutes after the last change', () => {
    rememberSettings({ metric: 'profit' })
    vi.advanceTimersByTime(20 * 60 * 1000)

    expect(recallSettings()).toBeNull()
  })

  it('keeps each кабинет separate', () => {
    rememberSettings({ nmIds: [1] })
    setWorkspaceId('ws-2')

    expect(recallSettings()).toBeNull()
  })

  it('starts on the defaults when storage holds something unreadable', () => {
    localStorage.setItem('heatmap:settings:ws-1', '{not json')

    expect(recallSettings()).toBeNull()
  })
})
