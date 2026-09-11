/**
 * The timeline's geometry.
 *
 * A bar is a claim about proportions, and a wrong proportion looks exactly like
 * a right one — which is why this is the part of the panel that is tested and
 * the markup around it is not. Four things can make the line lie: turns drawn
 * in the order the log returns them (newest first), an unfinished turn run on
 * past the moment the rotation stopped, a short turn drawn as nothing at all,
 * and widths that no longer sum to the track once the short ones are floored.
 */
import { describe, expect, it } from 'vitest'

import { buildTimeline, roundsIn } from '@/modules/abTests/timeline'

const NOW = Date.parse('2026-09-08T12:00:00Z')

/** One exposure row, as the detail endpoint serialises it. */
function turn(overrides = {}) {
  return {
    variant_id: '00000000-0000-7000-8000-00000000000a',
    position: 1,
    is_original: false,
    round_number: 1,
    activated_at: '2026-09-08T10:00:00Z',
    deactivated_at: '2026-09-08T11:00:00Z',
    views: 1000,
    clicks: 40,
    click_through: '4.00',
    ...overrides,
  }
}

describe('buildTimeline', () => {
  it('reads left to right although the log arrives newest first', () => {
    const { segments } = buildTimeline(
      [
        turn({ activated_at: '2026-09-08T11:00:00Z', deactivated_at: '2026-09-08T12:00:00Z' }),
        turn({ activated_at: '2026-09-08T10:00:00Z', deactivated_at: '2026-09-08T11:00:00Z' }),
      ],
      { endsAt: NOW },
    )

    expect(segments.map((s) => s.startMs)).toEqual([
      Date.parse('2026-09-08T10:00:00Z'),
      Date.parse('2026-09-08T11:00:00Z'),
    ])
    expect(segments[0].leftPercent).toBe(0)
  })

  it('cuts an unfinished turn off where the line ends', () => {
    // A pause leaves the photo on the card, so its exposure is never closed.
    // Measured to «сейчас» instead of to the stop, a test paused on Friday draws
    // a segment that eats the whole track by Monday.
    const { segments, live, endMs } = buildTimeline(
      [turn({ activated_at: '2026-09-08T11:30:00Z', deactivated_at: null })],
      { endsAt: NOW },
    )

    expect(live).toBe(true)
    expect(endMs).toBe(NOW)
    expect(segments[0].durationMs).toBe(30 * 60_000)
  })

  it('labels every turn, alternating above and below the track', () => {
    // Crowded labels used to be dropped, and what that hid was always the short
    // turns — the ones the timeline exists to make visible.
    const { segments } = buildTimeline(
      Array.from({ length: 6 }, (_, index) =>
        turn({
          activated_at: `2026-09-08T0${index + 3}:00:00Z`,
          deactivated_at: `2026-09-08T0${index + 4}:00:00Z`,
        }),
      ),
      { endsAt: NOW },
    )

    expect(segments.map((s) => s.above)).toEqual([true, false, true, false, true, false])
  })

  it('fills the track exactly, even after flooring a very short turn', () => {
    // Nine minutes inside a four-hour line is 3.75 % of it; the floor widens it
    // and everything else has to give the width back, or the last segment ends
    // past the end of the track.
    const { segments } = buildTimeline(
      [
        turn({ activated_at: '2026-09-08T08:00:00Z', deactivated_at: '2026-09-08T11:51:00Z' }),
        turn({ activated_at: '2026-09-08T11:51:00Z', deactivated_at: '2026-09-08T12:00:00Z' }),
      ],
      { endsAt: NOW },
    )

    const last = segments[segments.length - 1]
    expect(last.leftPercent + last.widthPercent).toBeCloseTo(100, 6)
    expect(segments[1].widthPercent).toBeGreaterThan(1)
  })

  it('shows one lap when one is picked', () => {
    const rows = [
      turn({ round_number: 2, activated_at: '2026-09-08T11:00:00Z' }),
      turn({ round_number: 1, activated_at: '2026-09-08T09:00:00Z' }),
    ]

    expect(buildTimeline(rows, { endsAt: NOW, round: 2 }).segments).toHaveLength(1)
    expect(buildTimeline(rows, { endsAt: NOW, round: 0 }).segments).toHaveLength(2)
  })

  it('names the baseline «Главное» and numbers the rest', () => {
    const { segments } = buildTimeline(
      [turn({ is_original: true, position: 0 }), turn({ position: 3 })],
      { endsAt: NOW },
    )

    expect(segments.map((s) => s.label)).toContain('Главное')
    expect(segments.map((s) => s.label)).toContain('Вариант 3')
  })

  it('is empty rather than broken for a test that has never installed anything', () => {
    expect(buildTimeline([], { endsAt: NOW })).toEqual({
      segments: [],
      startMs: null,
      endMs: null,
      totalMs: 0,
      live: false,
    })
  })
})

describe('roundsIn', () => {
  it('offers the laps that actually have turns, newest first', () => {
    expect(roundsIn([turn({ round_number: 1 }), turn({ round_number: 3 })])).toEqual([3, 1])
    expect(roundsIn([])).toEqual([])
  })
})
