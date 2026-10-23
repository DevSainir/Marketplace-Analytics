/**
 * The rotation timeline, as a panel.
 *
 * The geometry is proved in `timeline.spec.js`; what is left here is what the
 * component adds on top of it and what a reader would notice broken: where the
 * line is cut off for a test that is no longer running, that a turn is hoverable
 * at all and that the popup carries the figures which exist nowhere else on the
 * page, that the picker narrows the line to one lap, and that a test with no
 * turns says so instead of drawing an empty bar.
 */
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import RotationTimeline from '@/modules/abTests/components/RotationTimeline.vue'

const NOW = new Date('2026-09-08T12:00:00Z')
const MAIN = '00000000-0000-7000-8000-00000000000a'
const SECOND = '00000000-0000-7000-8000-00000000000b'

function turn(overrides = {}) {
  return {
    variant_id: SECOND,
    position: 1,
    is_original: false,
    round_number: 1,
    activated_at: '2026-09-08T10:00:00Z',
    deactivated_at: '2026-09-08T11:00:00Z',
    views: 1234,
    clicks: 56,
    click_through: '4.54',
    ...overrides,
  }
}

function mountIt(history, test = {}) {
  return mount(RotationTimeline, {
    props: { test: { id: 'x', status: 'running', history, ...test }, imageUrls: {} },
    attachTo: document.body,
  })
}

beforeEach(() => vi.useFakeTimers({ now: NOW }))
afterEach(() => {
  vi.useRealTimers()
  document.body.innerHTML = ''
})

describe('RotationTimeline', () => {
  it('ends a stopped test’s line at the stop, not at "now"', () => {
    // The open turn of a paused test would otherwise grow for as long as the
    // test stands, squeezing every turn that happened into the left edge.
    const wrapper = mountIt(
      [turn({ activated_at: '2026-09-08T11:00:00Z', deactivated_at: null }), turn()],
      { status: 'paused', stopped_at: '2026-09-08T11:30:00Z' },
    )

    expect(wrapper.get('[data-testid="timeline-total"]').text()).toContain('1 h 30 min')
    expect(wrapper.get('[data-testid="timeline-end"]').text()).not.toContain('now')
  })

  it('falls back to the last closed turn when no stop was recorded', () => {
    // Tests paused before `stopped_at` existed carry none, and "now" is an
    // unbounded guess where the last turn that did close is a bounded one.
    const wrapper = mountIt(
      [turn({ activated_at: '2026-09-08T11:00:00Z', deactivated_at: null }), turn()],
      { status: 'paused' },
    )

    expect(wrapper.get('[data-testid="timeline-total"]').text()).toContain('1 h 0 min')
  })

  it('labels every turn, on both sides of the track', () => {
    const wrapper = mountIt([
      turn({ activated_at: '2026-09-08T11:00:00Z', deactivated_at: '2026-09-08T12:00:00Z' }),
      turn(),
    ])

    expect(wrapper.findAll('[data-testid="timeline-marker"]')).toHaveLength(2)
  })

  it('draws one segment per turn', () => {
    const wrapper = mountIt([
      turn({ round_number: 2, activated_at: '2026-09-08T11:00:00Z', deactivated_at: null }),
      turn({ variant_id: MAIN, position: 0, is_original: true }),
    ])

    expect(wrapper.findAll('[data-testid="timeline-segment"]')).toHaveLength(2)
    expect(wrapper.get('[data-testid="timeline-total"]').text()).toContain('2 h 0 min')
    // The line is still running, so its right-hand end is "now" rather than
    // a stamp that would look like the test had finished.
    expect(wrapper.get('[data-testid="timeline-end"]').text()).toBe('now')
  })

  it('opens a turn’s figures on hover', async () => {
    const wrapper = mountIt([turn()])

    await wrapper.get('[data-testid="timeline-segment"]').trigger('mouseenter')

    const tip = document.querySelector('[role="tooltip"]')
    expect(tip).not.toBeNull()
    expect(tip.textContent).toContain('Variant 1')
    expect(tip.textContent).toContain('1 h 0 min')
    expect(tip.textContent).toContain('56')
    expect(tip.textContent).toContain('4.54%')

    await wrapper.get('[data-testid="timeline-segment"]').trigger('mouseleave')
    expect(document.querySelector('[role="tooltip"]')).toBeNull()
  })

  it('narrows the line to the picked lap', async () => {
    const wrapper = mountIt([
      turn({ round_number: 2, activated_at: '2026-09-08T11:00:00Z' }),
      turn({ round_number: 1 }),
    ])

    await wrapper.get('[data-testid="timeline-round"]').setValue('2')

    expect(wrapper.findAll('[data-testid="timeline-segment"]')).toHaveLength(1)
  })

  it('says nothing has been installed rather than drawing an empty bar', () => {
    const wrapper = mountIt([])

    expect(wrapper.findAll('[data-testid="timeline-segment"]')).toHaveLength(0)
    expect(wrapper.text()).toContain('No turns yet')
  })
})
