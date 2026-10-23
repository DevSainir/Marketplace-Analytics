/**
 * Chart geometry — the axis rounding and the point mapping.
 *
 * Pure functions, so they are pinned here rather than through a mounted chart.
 * The cases are the ones that decide whether a reader is misled: an axis that
 * ends on the data's own maximum, a gap drawn as a straight line, and a
 * negative series whose zero does not land on a grid line.
 */
import { buildScales, labelStep, linePath, niceMax, shortNumber } from './chartGeometry'

describe('niceMax', () => {
  it('rounds an axis up to a number a person would choose', () => {
    expect(niceMax(1_847_233)).toBe(2_000_000)
    expect(niceMax(23_400)).toBe(25_000)
    expect(niceMax(4_100)).toBe(5_000)
  })

  it('never returns zero, so a flat series still has an axis', () => {
    // A zero span would divide by zero in the scale and put every point on NaN.
    expect(niceMax(0)).toBe(1)
    expect(niceMax(-5)).toBe(1)
  })
})

describe('shortNumber', () => {
  it('shortens an axis tick without inventing precision', () => {
    expect(shortNumber(1_200_000)).toBe('1.2M')
    expect(shortNumber(23_400)).toBe('23K')
    expect(shortNumber(842)).toBe('842')
  })
})

describe('buildScales', () => {
  it('puts the zero rule on a grid line when a series goes negative', () => {
    // Rounding only the positive end would leave zero between two ticks, and a
    // margin chart is read against exactly that line.
    const scales = buildScales({
      width: 700,
      height: 232,
      series: [{ values: [100, -40] }],
      count: 2,
    })

    expect(scales.hasNegative).toBe(true)
    expect(scales.ticks.some((tick) => tick.value === 0)).toBe(true)
  })

  it('keeps the grid readable rather than stepping to the data', () => {
    // The step is chosen from the span, so a wildly different range must not
    // turn into twenty hairlines or into two.
    for (const values of [
      [0, 1_847_233],
      [100, -40],
      [0, 900],
      [-5, -120],
      [7, 7],
    ]) {
      const scales = buildScales({ width: 700, height: 232, series: [{ values }], count: 2 })

      expect(scales.ticks.length).toBeGreaterThanOrEqual(3)
      expect(scales.ticks.length).toBeLessThanOrEqual(7)
    }
  })

  it('keeps a single-point window on the plot instead of on its left edge', () => {
    const scales = buildScales({ width: 700, height: 232, series: [{ values: [5] }], count: 1 })

    expect(scales.x(0)).toBeGreaterThan(58)
    expect(scales.x(0)).toBeLessThan(700)
  })

  it('survives a container that has not been laid out yet', () => {
    // A hidden tab measures zero; without the clamp every path command is NaN.
    const scales = buildScales({ width: 0, height: 0, series: [{ values: [1] }], count: 3 })

    expect(Number.isFinite(scales.x(1))).toBe(true)
    expect(Number.isFinite(scales.y(1))).toBe(true)
  })
})

describe('linePath', () => {
  it('breaks the line where a day has no measurement', () => {
    // Joining across a gap would draw through days nobody harvested and make
    // the coverage look complete.
    const path = linePath(
      [1, null, 3],
      (index) => index * 10,
      (value) => value,
    )

    expect(path.startsWith('M0.0 1.0')).toBe(true)
    expect(path).toContain('M20.0 3.0')
    expect(path).not.toContain('L20.0 3.0')
  })

  it('is empty rather than malformed when nothing is measured', () => {
    expect(
      linePath(
        [null, null],
        (index) => index,
        (value) => value,
      ),
    ).toBe('')
  })
})

describe('labelStep', () => {
  it('thins the date labels so they cannot overlap', () => {
    expect(labelStep(54, 640)).toBeGreaterThan(1)
    expect(labelStep(5, 640)).toBe(1)
  })
})
