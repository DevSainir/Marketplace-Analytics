import { flushPromises, mount } from '@vue/test-utils'

import BackfillProgress from '@/modules/profile/components/BackfillProgress.vue'
import { fetchBackfillStatus } from '@/modules/profile/api'

vi.mock('@/modules/profile/api', () => ({ fetchBackfillStatus: vi.fn() }))

/** One lane row in the shape the endpoint serves. */
function lane(overrides = {}) {
  return {
    lane: 'funnel',
    label: 'Воронка продаж',
    state: 'running',
    done_units: 73,
    total_units: 365,
    percent: 20,
    message: 'Собираем воронку: 73 из 365 дней.',
    updated_at: '2026-09-10T11:00:00Z',
    ...overrides,
  }
}

function mountPanel() {
  return mount(BackfillProgress, { props: { workspaceId: 'ws-1' } })
}

describe('BackfillProgress', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    fetchBackfillStatus.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows a lane per module while the backfill is running', async () => {
    // Four lanes, not one bar: the P&L lane runs for hours after the others
    // have finished, and a single percentage would be wrong about all four.
    fetchBackfillStatus.mockResolvedValue({
      active: true,
      lanes: [lane(), lane({ lane: 'pnl', label: 'Финансы (P&L)', percent: 3 })],
    })

    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('Воронка продаж')
    expect(wrapper.text()).toContain('Финансы (P&L)')
  })

  it('hides itself once every lane is done', async () => {
    // A workspace backfilled last month must not carry a permanent «готово»
    // block down its profile — the panel exists to explain a wait.
    fetchBackfillStatus.mockResolvedValue({
      active: false,
      lanes: [lane({ state: 'done', percent: 100 })],
    })

    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.find('section').exists()).toBe(false)
  })

  it('keeps showing a failed lane after the run stops', async () => {
    // The one thing worth surfacing afterwards: a lane that failed is data the
    // seller does not have and would otherwise never be told about.
    fetchBackfillStatus.mockResolvedValue({
      active: false,
      lanes: [lane({ state: 'failed', message: 'Нет токена «Продвижение».' })],
    })

    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('ошибка')
  })

  it('stops polling once nothing is moving', async () => {
    // A timer left running re-asks forever on a finished workspace, on every
    // profile visit, for as long as the tab is open.
    fetchBackfillStatus.mockResolvedValue({ active: false, lanes: [lane({ state: 'done' })] })

    mountPanel()
    await flushPromises()
    vi.advanceTimersByTime(60000)
    await flushPromises()

    expect(fetchBackfillStatus).toHaveBeenCalledTimes(1)
  })

  it('keeps polling through a failed request instead of freezing', async () => {
    // A 502 during a deploy must not leave the panel stuck for the session:
    // the backfill runs server-side whatever this component manages to read.
    fetchBackfillStatus
      .mockResolvedValueOnce({ active: true, lanes: [lane()] })
      .mockRejectedValueOnce(new Error('502'))
      .mockResolvedValue({ active: true, lanes: [lane({ percent: 25 })] })

    mountPanel()
    await flushPromises()
    vi.advanceTimersByTime(15000)
    await flushPromises()
    vi.advanceTimersByTime(15000)
    await flushPromises()

    expect(fetchBackfillStatus).toHaveBeenCalledTimes(3)
  })
})
