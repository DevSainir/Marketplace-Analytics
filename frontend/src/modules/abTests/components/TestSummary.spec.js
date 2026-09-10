/**
 * The «Итог по тесту» panel.
 *
 * The panel's value is that its figures can be checked against the table under
 * it, so what is worth pinning is everything that would make it disagree with
 * that table or with itself: a CTR averaged instead of divided, a «Прошло»
 * frozen at the last poll, and an idle stretch rendered as a negative number
 * when the browser's clock and the server's summed intervals disagree by a few
 * seconds.
 */
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import TestSummary from '@/modules/abTests/components/TestSummary.vue'

/** `toLocaleString('ru-RU')` groups with U+00A0; normalise rather than paste it. */
const plain = (text) => text.replace(/\u00a0/g, ' ')

const NOW = new Date('2026-09-08T23:00:00Z')

function test(overrides = {}, summary = {}) {
  return {
    id: '00000000-0000-7000-8000-000000000001',
    status: 'running',
    started_at: '2026-09-08T13:00:00Z',
    finished_at: null,
    ...overrides,
    summary: {
      views: 12_345,
      clicks: 456,
      atbs: 20,
      orders: 7,
      spend: '3050.40',
      click_through: '3.69',
      add_to_cart: '4.39',
      order_rate: '35.00',
      measured_minutes: 540, // 9 h of the 10 h since the start
      windows: 108,
      first_window_at: '2026-09-08T13:00:00Z',
      last_window_at: '2026-09-08T22:55:00Z',
      rounds_completed: 4,
      variants_measured: 6,
      variants_total: 8,
      ...summary,
    },
  }
}

describe('TestSummary', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW)
  })
  afterEach(() => vi.useRealTimers())

  it('shows the totals as the backend summed them', () => {
    const wrapper = mount(TestSummary, { props: { test: test() } })

    expect(plain(wrapper.get('[data-testid="summary-views"]').text())).toBe('12 345')
    expect(plain(wrapper.get('[data-testid="summary-clicks"]').text())).toBe('456')
    expect(plain(wrapper.get('[data-testid="summary-ctr"]').text())).toBe('3.69 %')
    expect(plain(wrapper.get('[data-testid="summary-spend"]').text())).toBe('3 050 ₽')
  })

  it('renders an unmeasured CTR as «—» rather than as 0 %', () => {
    const wrapper = mount(TestSummary, {
      props: { test: test({}, { views: 0, clicks: 0, click_through: null }) },
    })

    expect(wrapper.get('[data-testid="summary-ctr"]').text()).toBe('—')
  })

  it('counts elapsed time to now for a live test and to the finish for a closed one', () => {
    const live = mount(TestSummary, { props: { test: test() } })
    expect(plain(live.text())).toContain('10 ч 0 мин')

    const done = mount(TestSummary, {
      props: {
        test: test({ status: 'cancelled', finished_at: '2026-09-08T19:30:00Z' }),
      },
    })
    // Fixed by the finish, not by the reader's clock three hours later.
    expect(plain(done.text())).toContain('6 ч 30 мин')
  })

  it('separates measured time from elapsed time', () => {
    const wrapper = mount(TestSummary, { props: { test: test() } })

    const text = plain(wrapper.text())
    expect(text).toContain('Прошло')
    expect(text).toContain('10 ч 0 мин')
    expect(text).toContain('Измерено')
    expect(text).toContain('9 ч 0 мин')
  })

  it('never reports a negative idle stretch when the two clocks disagree', async () => {
    // Measured longer than elapsed: impossible in principle, reachable in
    // practice through a browser clock that is a minute behind the server's.
    const wrapper = mount(TestSummary, { props: { test: test({}, { measured_minutes: 700 }) } })

    await wrapper.get('[data-testid="summary-explain"]').trigger('click')
    expect(plain(wrapper.text())).not.toContain('-')
  })

  it('spells out the derivation on request', async () => {
    const wrapper = mount(TestSummary, { props: { test: test() } })

    expect(plain(wrapper.text())).not.toContain('÷')
    await wrapper.get('[data-testid="summary-explain"]').trigger('click')

    const text = plain(wrapper.text())
    expect(text).toContain('456 ÷ 12 345')
    expect(text).toContain('108')
  })

  it('says how much of the test has actually run', () => {
    const wrapper = mount(TestSummary, { props: { test: test() } })

    expect(plain(wrapper.text())).toContain('6 фото из 8')
    expect(plain(wrapper.text())).toContain('кругов пройдено 4')
  })
})
