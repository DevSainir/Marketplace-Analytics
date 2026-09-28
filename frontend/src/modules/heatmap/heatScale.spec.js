/**
 * The heatmap's colour rule: which end of a range is good, and when a cell is
 * left unpainted.
 *
 * The direction is the part worth pinning — a ДРР painted green at its highest
 * would tell a seller the opposite of the truth, and nothing else on the screen
 * would contradict it.
 */
import { heatColor, heatPosition, rangeOf } from './heatScale'

describe('rangeOf', () => {
  it('ignores the cells with no value', () => {
    expect(rangeOf([3, null, 10, undefined, 7])).toEqual({ min: 3, max: 10 })
  })

  it('has no range when no cell carries a value', () => {
    expect(rangeOf([null, null])).toBeNull()
  })
})

describe('heatPosition', () => {
  it('puts the highest value at the good end when more is better', () => {
    expect(heatPosition(10, { min: 0, max: 10 }, 'up')).toBe(1)
  })

  it('puts the highest value at the bad end when less is better', () => {
    expect(heatPosition(10, { min: 0, max: 10 }, 'down')).toBe(0)
  })

  it('places nothing when every cell is equal', () => {
    expect(heatPosition(5, { min: 5, max: 5 }, 'up')).toBeNull()
  })

  it('places nothing for a missing value', () => {
    expect(heatPosition(null, { min: 0, max: 10 }, 'up')).toBeNull()
  })
})

describe('heatColor', () => {
  it('paints the good end green', () => {
    expect(heatColor(1, 'up')).toContain('--ui-pos-rgb')
  })

  it('paints the bad end red', () => {
    expect(heatColor(0, 'up')).toContain('--ui-neg-rgb')
  })

  it('leaves the middle of the range unpainted', () => {
    expect(heatColor(0.5, 'up')).toBe('')
  })

  it('paints a metric with no better end in the action hue', () => {
    expect(heatColor(1, 'neutral')).toContain('--ui-action-rgb')
  })
})
