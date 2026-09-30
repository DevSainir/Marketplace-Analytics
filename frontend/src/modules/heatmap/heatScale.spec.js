/**
 * The heatmap's colour rule: a cell is painted by where it sits between the
 * median of the cells it is compared with and the extreme on its side.
 *
 * Pinned: the norm is the median, not the middle of the range; every cell off
 * the norm gets a tint; a spike deepens only its own side; and the direction
 * still says which side is good.
 */
import { departure, heatStyle, scaleOf } from './heatScale'

describe('scaleOf', () => {
  it('takes the median as the norm, so one outlier does not move it', () => {
    expect(scaleOf([2, 3, 3, 4, 40])).toEqual({ min: 2, median: 3, max: 40 })
  })

  it('has no scale when every cell is equal', () => {
    expect(scaleOf([5, null, 5])).toBeNull()
  })
})

describe('departure', () => {
  it('is zero at the norm and full at either extreme', () => {
    const scale = scaleOf([2, 3, 3, 4, 40])
    expect(departure(3, scale)).toBe(0)
    expect(departure(2, scale)).toBe(-1)
    expect(departure(40, scale)).toBe(1)
  })

  it('lets a spike deepen only its own side', () => {
    const scale = scaleOf([2, 3, 3, 4, 40])
    expect(departure(4, scale)).toBeLessThan(0.05)
  })
})

describe('heatStyle', () => {
  const scale = scaleOf([10, 20, 30])

  it('paints a rise green when more is better', () => {
    expect(heatStyle(25, scale, 'up').background).toContain('--ui-pos-rgb')
  })

  it('paints a rise red when less is better', () => {
    expect(heatStyle(25, scale, 'down').background).toContain('--ui-neg-rgb')
  })

  it('leaves only a cell exactly at the norm white', () => {
    expect(heatStyle(20, scale, 'up')).toEqual({})
    expect(heatStyle(20.5, scale, 'up').background).toBeDefined()
  })

  it('never prints the figure white', () => {
    expect(heatStyle(10, scale, 'up').color).toBeUndefined()
  })

  it('paints a metric with no better end by magnitude in the action hue', () => {
    expect(heatStyle(10, scale, 'neutral')).toEqual({})
    expect(heatStyle(30, scale, 'neutral').background).toContain('--ui-action-rgb')
  })
})
