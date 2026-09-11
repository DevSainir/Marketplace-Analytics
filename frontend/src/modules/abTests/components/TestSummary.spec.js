/**
 * The «Итог по тесту» panel.
 *
 * The panel's value is that its figures can be checked against the table under
 * it, so what is worth pinning is everything that would make it disagree with
 * that table or with itself: a CTR averaged instead of divided, and a duration
 * that quietly becomes wall-clock time.
 *
 * «Длительность» is the summed length of the measured intervals — NOT the time
 * since the start. The two used to sit side by side, and dropping the wall
 * clock is what makes it possible to read this one as the wrong thing: nine
 * hours of data over a fourteen-hour test must keep saying nine.
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TestSummary from '@/modules/abTests/components/TestSummary.vue'

/** `toLocaleString('ru-RU')` groups with U+00A0; normalise rather than paste it. */
const plain = (text) => text.replace(/\u00a0/g, ' ')

const VARIANT_MAIN = '00000000-0000-7000-8000-00000000000a'

function test(overrides = {}, summary = {}) {
  return {
    id: '00000000-0000-7000-8000-000000000001',
    status: 'running',
    started_at: '2026-09-08T13:00:00Z',
    finished_at: null,
    stopped_at: null,
    active_variant_id: VARIANT_MAIN,
    variants: [{ variant_id: VARIANT_MAIN, position: 0, is_original: true }],
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

  it('reports the measured exposure, not the time since the start', () => {
    const wrapper = mount(TestSummary, { props: { test: test() } })

    const text = plain(wrapper.text())
    expect(text).toContain('Длительность')
    expect(text).toContain('9 ч 0 мин')
    expect(text).not.toContain('10 ч 0 мин')
  })

  it('says when the rotation stopped, pause included', () => {
    const wrapper = mount(TestSummary, {
      props: { test: test({ status: 'paused', stopped_at: '2026-09-08T19:30:00Z' }) },
    })

    // A paused test has no finish, so the stop is the only clock that answers
    // «сколько оно уже стоит». Asserted as "not «—»" rather than against a
    // rendered time: the panel formats in the reader's own zone, and CI's is
    // not the developer's.
    expect(plain(wrapper.text())).toContain('Остановлен')
    expect(wrapper.get('[data-testid="fact-stopped"]').text()).not.toBe('—')
  })

  it('leaves «Остановлен» empty while the test is running', () => {
    const wrapper = mount(TestSummary, { props: { test: test() } })

    expect(wrapper.get('[data-testid="fact-stopped"]').text()).toBe('—')
    expect(wrapper.find('[data-testid="summary-status"]').exists()).toBe(false)
  })

  it('explains a stop caused by somebody editing the card', () => {
    const wrapper = mount(TestSummary, {
      props: {
        test: test({
          status: 'paused',
          stopped_at: '2026-09-09T11:58:18Z',
          photo_conflict_at: '2026-09-09T11:58:18Z',
        }),
      },
    })

    // The one stop the rotation will not undo by itself, so the reason has to
    // be on the screen: «На паузе» alone reads as «сломалось».
    const text = plain(wrapper.get('[data-testid="summary-photo-conflict"]').text())
    expect(text).toContain('поменяли вручную')
    expect(text).toContain('ни одному варианту не зачтён')
  })

  it('says nothing about a conflict when there was none', () => {
    const wrapper = mount(TestSummary, { props: { test: test({ status: 'paused' }) } })

    expect(wrapper.find('[data-testid="summary-photo-conflict"]').exists()).toBe(false)
  })

  it('names a stopped test’s status beside the heading', () => {
    const wrapper = mount(TestSummary, { props: { test: test({ status: 'paused' }) } })

    expect(wrapper.get('[data-testid="summary-status"]').text()).toBe('На паузе')
  })

  it('says how much of the test has actually run, and what is up now', () => {
    const wrapper = mount(TestSummary, { props: { test: test() } })

    const text = plain(wrapper.text())
    expect(text).toContain('6 фото из 8')
    expect(text).toContain('кругов пройдено 4')
    expect(text).toContain('Сейчас на карточке')
    expect(wrapper.get('[data-testid="summary-live-photo"]').text()).toContain('Главное')
  })
})
