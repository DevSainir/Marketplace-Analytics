/**
 * The heatmap's colour rule: a cell is painted by how far it sits from the
 * norm of the cells it is compared with, and an ordinary day is not painted.
 *
 * The old rule placed every cell between the worst and the best, so a flat
 * week of 14-15-16 always had a red day and a green one. What is pinned here is
 * that a flat row stays white, a real departure is painted, the tint grows
 * gently, and the direction still says which side is good.
 */
import { departure, heatColor, normOf } from './heatScale'

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
    const norm = normOf([5, 5, 6, 4, 5])
    expect(departure(3, norm, { count: true })).toBe(0)
  })

  it('marks a real drop below the norm as negative', () => {
    expect(departure(4, normOf([10, 10, 10]))).toBeLessThan(0)
  })

  it('keeps a day half again above the norm a light tint', () => {
    expect(departure(15 * 1.5, normOf([15, 15, 15]))).toBeLessThan(0.4)
  })

  it('grows with the distance', () => {
    const norm = normOf([10, 10, 10])
    expect(departure(30, norm)).toBeGreaterThan(departure(18, norm))
  })
})

describe('heatColor', () => {
  it('paints a rise green when more is better', () => {
    expect(heatColor(0.6, 'up')).toContain('--ui-pos-rgb')
  })

  it('paints a rise red when less is better', () => {
    expect(heatColor(0.6, 'down')).toContain('--ui-neg-rgb')
  })

  it('leaves a cell in the normal band unpainted', () => {
    expect(heatColor(0, 'up')).toBe('')
  })

  it('paints a metric with no better end in the action hue', () => {
    expect(heatColor(-0.6, 'neutral')).toContain('--ui-action-rgb')
  })
})
