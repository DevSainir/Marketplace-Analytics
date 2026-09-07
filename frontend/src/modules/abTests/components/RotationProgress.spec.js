/**
 * The rotation progress panel.
 *
 * What is worth pinning is the arithmetic and the states it must not lie in.
 * A bar is a claim about how far along something is, and the two ways it can
 * mislead are both cheap to test: a countdown that runs negative once a slot
 * has elapsed (the swap waits for the next Celery pass, so this is the *normal*
 * end state, not an edge case), and a bar that shows progress for a test which
 * has none.
 */
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import RotationProgress from '@/modules/abTests/components/RotationProgress.vue'

/**
 * `toLocaleString('ru-RU')` groups thousands with a non-breaking space, so a
 * literal typed with an ordinary one never matches. Normalise rather than
 * pasting U+00A0 into the source, where it is invisible to the next reader.
 */
const plain = (text) => text.replace(/\u00a0/g, ' ')

const NOW = new Date('2026-09-07T12:00:00Z')
const VARIANT_MAIN = '00000000-0000-7000-8000-00000000000a'
const VARIANT_ONE = '00000000-0000-7000-8000-00000000000b'

function test(overrides = {}) {
  return {
    id: '00000000-0000-7000-8000-000000000001',
    status: 'running',
    trigger_mode: 'time',
    slot_minutes: 20,
    impression_budget: 10_000,
    active_variant_id: VARIANT_MAIN,
    active_since: '2026-09-07T11:52:00Z', // 8 of 20 minutes gone
    variants: [
      { variant_id: VARIANT_MAIN, position: 0, is_original: true, is_active: true, views: 0 },
      { variant_id: VARIANT_ONE, position: 1, is_original: false, is_active: false, views: 0 },
    ],
    ...overrides,
  }
}

const mountIt = (overrides) => mount(RotationProgress, { props: { test: test(overrides) } })

beforeEach(() => vi.useFakeTimers({ now: NOW }))
afterEach(() => vi.useRealTimers())

describe('the time trigger', () => {
  it('counts the slot down from when this photo went up', () => {
    const wrapper = mountIt()

    expect(plain(wrapper.get('[data-testid="rotation-measure"]').text())).toBe(
      'Осталось 12:00 из 20 мин',
    )
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('40')
  })

  it('says the slot is served rather than running the clock negative', () => {
    // The swap happens on the next five-minute pass, so "elapsed but still up"
    // is where a time-triggered test spends part of every turn.
    const wrapper = mountIt({ active_since: '2026-09-07T11:30:00Z' })

    expect(wrapper.get('[data-testid="rotation-measure"]').text()).toBe('Слот отработан')
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('100')
    expect(wrapper.text()).toContain('сменится на ближайшем проходе')
  })

  it('ticks without a request', async () => {
    const wrapper = mountIt()

    await vi.advanceTimersByTimeAsync(60_000)

    expect(plain(wrapper.get('[data-testid="rotation-measure"]').text())).toBe(
      'Осталось 11:00 из 20 мин',
    )
  })
})

describe('the impression trigger', () => {
  it('measures the live photo against the budget', () => {
    const wrapper = mountIt({
      trigger_mode: 'impressions',
      active_variant_id: VARIANT_ONE,
      variants: [
        {
          variant_id: VARIANT_MAIN,
          position: 0,
          is_original: true,
          is_active: false,
          views: 10_000,
        },
        { variant_id: VARIANT_ONE, position: 1, is_original: false, is_active: true, views: 2_500 },
      ],
    })

    expect(plain(wrapper.get('[data-testid="rotation-measure"]').text())).toBe(
      '2 500 из 10 000 показов',
    )
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('25')
  })
})

describe('what it names', () => {
  it('calls the captured photo «Главное» and places it in the circle', () => {
    const wrapper = mountIt()

    expect(wrapper.text()).toContain('Главное')
    expect(wrapper.text()).toContain('Фото 1 из 2')
  })

  it('numbers an uploaded photo', () => {
    const wrapper = mountIt({ active_variant_id: VARIANT_ONE })

    expect(wrapper.text()).toContain('Вариант 1')
    expect(wrapper.text()).toContain('Фото 2 из 2')
  })
})

describe('when there is no turn in progress', () => {
  it.each(['draft', 'completed', 'cancelled'])('renders nothing for a %s test', (status) => {
    const wrapper = mountIt({ status, active_variant_id: null, active_since: null })

    expect(wrapper.find('[data-testid="rotation-progress"]').exists()).toBe(false)
  })

  it('keeps the panel on a paused test and says the time is not counted', () => {
    const wrapper = mountIt({ status: 'paused' })

    expect(wrapper.find('[data-testid="rotation-progress"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('не засчитываются')
  })
})
