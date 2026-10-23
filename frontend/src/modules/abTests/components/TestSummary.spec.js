/**
 * The "Test summary" panel.
 *
 * The panel's value is that its figures can be checked against the table under
 * it, so what is worth pinning is everything that would make it disagree with
 * that table or with itself: a CTR averaged instead of divided, and a duration
 * that quietly becomes wall-clock time.
 *
 * "Duration" is the summed length of the measured intervals — NOT the time
 * since the start. The two used to sit side by side, and dropping the wall
 * clock is what makes it possible to read this one as the wrong thing: nine
 * hours of data over a fourteen-hour test must keep saying nine.
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TestSummary from '@/modules/abTests/components/TestSummary.vue'

/** Collapse any U+00A0 a formatter puts in, so the assertions read as plain text. */
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
    const wrapper = mount(TestSummary, { props: { test: test(), currency: 'KGS' } })

    expect(plain(wrapper.get('[data-testid="summary-views"]').text())).toBe('12,345')
    expect(plain(wrapper.get('[data-testid="summary-clicks"]').text())).toBe('456')
    expect(plain(wrapper.get('[data-testid="summary-ctr"]').text())).toBe('3.69%')
    expect(plain(wrapper.get('[data-testid="summary-spend"]').text())).toBe('KGS 3,050')
  })

  it('prints the spend bare while the currency is unknown', () => {
    // A workspace may advertise in KGS; the panel used to print a rouble sign.
    const unknown = mount(TestSummary, { props: { test: test() } })

    expect(plain(unknown.get('[data-testid="summary-spend"]').text())).toBe('3,050')
  })

  it('renders an unmeasured CTR as "—" rather than as 0%', () => {
    const wrapper = mount(TestSummary, {
      props: { test: test({}, { views: 0, clicks: 0, click_through: null }) },
    })

    expect(wrapper.get('[data-testid="summary-ctr"]').text()).toBe('—')
  })

  it('reports the measured exposure, not the time since the start', () => {
    const wrapper = mount(TestSummary, { props: { test: test() } })

    const text = plain(wrapper.text())
    expect(text).toContain('Duration')
    expect(text).toContain('9 h 0 min')
    expect(text).not.toContain('10 h 0 min')
  })

  it('says when the rotation stopped, pause included', () => {
    const wrapper = mount(TestSummary, {
      props: { test: test({ status: 'paused', stopped_at: '2026-09-08T19:30:00Z' }) },
    })

    // A paused test has no finish, so the stop is the only clock that answers
    // "how long has it been standing". Asserted as "not —" rather than against a
    // rendered time: the panel formats in the reader's own zone, and CI's is
    // not the developer's.
    expect(plain(wrapper.text())).toContain('Stopped')
    expect(wrapper.get('[data-testid="fact-stopped"]').text()).not.toBe('—')
  })

  it('leaves "Stopped" empty while the test is running', () => {
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
    // be on the screen: "Paused" alone reads as "broken".
    const text = plain(wrapper.get('[data-testid="summary-photo-conflict"]').text())
    expect(text).toContain('changed by hand')
    expect(text).toContain('counts for no variant')
  })

  it('explains a stop caused by the advertising, and that it resumes by itself', () => {
    const wrapper = mount(TestSummary, {
      props: {
        test: test({ status: 'paused', stopped_at: '2026-09-28T03:05:00Z', paused_by_ads: true }),
      },
    })

    // Without the sentence a seller presses "Start", the next pass pauses
    // it again, and the page reads as a test that pauses on its own.
    const text = plain(wrapper.get('[data-testid="summary-paused-by-ads"]').text())
    expect(text).toContain('no ads are running')
    expect(text).toContain('or missing')
    expect(text).toContain('resumes on its own')
    expect(wrapper.get('[data-testid="summary-status"]').text()).toBe('Paused · no ads')
  })

  it('does not blame the advertising for a pause the seller made', () => {
    const wrapper = mount(TestSummary, { props: { test: test({ status: 'paused' }) } })

    expect(wrapper.find('[data-testid="summary-paused-by-ads"]').exists()).toBe(false)
  })

  it('says nothing about a conflict when there was none', () => {
    const wrapper = mount(TestSummary, { props: { test: test({ status: 'paused' }) } })

    expect(wrapper.find('[data-testid="summary-photo-conflict"]').exists()).toBe(false)
  })

  it('names a stopped test’s status beside the heading', () => {
    const wrapper = mount(TestSummary, { props: { test: test({ status: 'paused' }) } })

    expect(wrapper.get('[data-testid="summary-status"]').text()).toBe('Paused')
  })

  it('says how much of the test has actually run, and what is up now', () => {
    const wrapper = mount(TestSummary, { props: { test: test() } })

    const text = plain(wrapper.text())
    expect(text).toContain('Impressions on 6 of 8 photos')
    expect(text).toContain('4 rounds completed')
    expect(text).toContain('On the card now')
    expect(wrapper.get('[data-testid="summary-live-photo"]').text()).toContain('Main photo')
  })
})

describe('the per-campaign fork', () => {
  const CAMPAIGNS = [
    {
      campaign_id: 97455930,
      name: 'Unified bid',
      kind: 'uni',
      views: 9000,
      clicks: 300,
      click_through: '3.33',
      spend: '2000.00',
    },
    {
      campaign_id: 97730900,
      name: 'CPC — search',
      kind: 'cpc',
      views: 3345,
      clicks: 156,
      click_through: '4.66',
      spend: '1050.40',
    },
  ]

  it('takes every figure apart when two campaigns paid for the traffic', () => {
    const wrapper = mount(TestSummary, { props: { test: test({ campaigns: CAMPAIGNS }) } })

    const forks = wrapper.findAll('[data-testid="tile-branches"]')
    expect(forks).toHaveLength(4)
    // The branches are the trunk taken apart, so they have to add back up to it.
    const views = plain(forks[0].text())
    expect(views).toContain('9,000')
    expect(views).toContain('3,345')
  })

  it('names each branch by its KIND, not by what the seller called the campaign', () => {
    // Under a figure four branches wide there is room for about eight
    // characters, and a seller's own "M-BLK-2 auto funnel Sep" arrived as
    // "M-B…" on every branch. What the fork is for is "Unified against CPC".
    const wrapper = mount(TestSummary, { props: { test: test({ campaigns: CAMPAIGNS }) } })

    const views = plain(wrapper.findAll('[data-testid="tile-branches"]')[0].text())
    expect(views).toContain('Unified')
    expect(views).toContain('CPC')
    expect(views).not.toContain('Unified bid')
  })

  it('keeps the campaign own name a hover away', () => {
    const wrapper = mount(TestSummary, { props: { test: test({ campaigns: CAMPAIGNS }) } })

    const names = wrapper
      .findAll('[data-testid="tile-branches"]')[0]
      .findAll('.ab-tile__branch-name')
      .map((node) => node.attributes('title'))

    expect(names).toEqual(['Unified bid', 'CPC — search'])
  })

  it('stays the plain figure it always was while only one campaign is running', () => {
    const wrapper = mount(TestSummary, { props: { test: test({ campaigns: [CAMPAIGNS[0]] }) } })

    expect(wrapper.find('[data-testid="tile-branches"]').exists()).toBe(false)
  })
})
