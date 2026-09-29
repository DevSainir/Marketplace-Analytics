/**
 * The heatmap's colour rule: a cell is painted by how far it sits from the
 * norm of the cells it is compared with, and an ordinary day is not painted.
 *
 * Pinned: a flat row stays white, distance is a ratio (half the norm is as far
 * as twice it), a collapse reads as a collapse, and the direction still says
 * which side is good.
 */
import { departure, heatStyle, normOf } from './heatScale'

describe('normOf', () => {
  it('takes the median, so one outlier does not move the norm', () => {
    expect(normOf([10, 11, 12, 500]).median).toBe(11.5)
  })

  it('has no norm with fewer than three values', () => {
    expect(normOf([3, null, 10])).toBeNull()
  })
})

describe('departure', () => {
  it('leaves an ordinary day inside the normal band unpainted', () => {
    const norm = normOf([14, 15, 15, 16])
    expect(departure(16, norm)).toBe(0)
    expect(departure(13, norm)).toBe(0)
  })

  it('treats a small count as noise within the square root of its norm', () => {
    expect(departure(3, normOf([5, 5, 6, 4, 5]), { count: true })).toBe(0)
  })

  it('reads 30 orders against a norm of 77 as a collapse, not a dip', () => {
    expect(departure(30, normOf([77, 77, 80]), { count: true })).toBeLessThan(-0.85)
  })

  it('weighs half the norm the same as twice the norm', () => {
    const norm = normOf([10, 10, 10])
    expect(departure(5, norm)).toBeCloseTo(-departure(20, norm), 6)
  })

  it('keeps a day half again above the norm short of full strength', () => {
    expect(departure(15, normOf([10, 10, 10]))).toBeLessThan(0.5)
  })

  it('paints a price move a count would shrug off', () => {
    const norm = normOf([1000, 1000, 1000])
    expect(departure(1100, norm, { band: 0.05 })).toBeGreaterThan(0)
    expect(departure(1100, norm)).toBe(0)
  })

  it('reads a zero against a positive norm as the bottom of the scale', () => {
    expect(departure(0, normOf([10, 10, 10]))).toBe(-1)
  })
})

describe('heatStyle', () => {
  it('paints a rise green when more is better', () => {
    expect(heatStyle(0.6, 'up').background).toContain('--ui-pos-rgb')
  })

  it('paints a rise red when less is better', () => {
    expect(heatStyle(0.6, 'down').background).toContain('--ui-neg-rgb')
  })

  it('leaves a cell in the normal band unpainted', () => {
    expect(heatStyle(0, 'up')).toEqual({})
  })

  it('prints the figure white on a strong tint so it stays legible', () => {
    expect(heatStyle(-0.9, 'up').color).toBe('#fff')
    expect(heatStyle(-0.2, 'up').color).toBeUndefined()
  })

  it('paints a metric with no better end in the action hue', () => {
    expect(heatStyle(-0.6, 'neutral').background).toContain('--ui-action-rgb')
  })
})
