/**
 * The timeline's geometry.
 *
 * A bar is a claim about proportions, and a wrong proportion looks exactly like
 * a right one — which is why this is the part of the panel that is tested and
 * the markup around it is not. Four things can make the line lie: turns drawn
 * in the order the log returns them (newest first), a live turn drawn as zero
 * width, a short turn drawn as nothing at all, and widths that no longer sum to
 * the track once the short ones have been floored.
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
      { now: NOW },
    )

    expect(segments.map((s) => s.startMs)).toEqual([
      Date.parse('2026-09-08T10:00:00Z'),
      Date.parse('2026-09-08T11:00:00Z'),
    ])
    expect(segments[0].leftPercent).toBe(0)
  })

  it('measures the open turn to the reader’s clock', () => {
    const { segments, live, endMs } = buildTimeline(
      [turn({ activated_at: '2026-09-08T11:30:00Z', deactivated_at: null })],
      { now: NOW },
    )

    expect(live).toBe(true)
    expect(endMs).toBe(NOW)
    expect(segments[0].durationMs).toBe(30 * 60_000)
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
      { now: NOW },
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

    expect(buildTimeline(rows, { now: NOW, round: 2 }).segments).toHaveLength(1)
    expect(buildTimeline(rows, { now: NOW, round: 0 }).segments).toHaveLength(2)
  })

  it('names the baseline «Главное» and numbers the rest', () => {
    const { segments } = buildTimeline(
      [turn({ is_original: true, position: 0 }), turn({ position: 3 })],
      { now: NOW },
    )

    expect(segments.map((s) => s.label)).toContain('Главное')
    expect(segments.map((s) => s.label)).toContain('Вариант 3')
  })

  it('is empty rather than broken for a test that has never installed anything', () => {
    expect(buildTimeline([], { now: NOW })).toEqual({
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
