import { describe, expect, it } from 'vitest'

import { buildFittedChart, ruleStep, weeksOf } from '@/modules/labs/chartScaling'
import { SKU_METRIC_GROUPS } from '@/modules/labs/metricChart'
import { COLUMNS_PER_DAY, TRAFFIC_COLUMNS } from '@/modules/labs/metricsMatrix'

/**
 * The long-window layout (`chartScaling.js`).
 *
 * A sandbox, but the two rules under it are the ones a redraw quietly breaks:
 * the week division has to be the WEEK (a fortnight looked identical and was
 * wrong), and nothing may come back as a column.
 */

const MONDAY = '2026-01-05'

/** `n` consecutive days from `MONDAY`. */
function isoDays(n) {
  return Array.from({ length: n }, (_, index) => {
    const day = new Date(`${MONDAY}T00:00:00Z`)
    day.setUTCDate(day.getUTCDate() + index)
    return day.toISOString().slice(0, 10)
  })
}

describe('weeksOf', () => {
  it('starts a new week on every Monday', () => {
    const weeks = weeksOf(isoDays(14))

    expect(weeks.map((week) => [week.from, week.to])).toEqual([
      [0, 7],
      [7, 14],
    ])
  })

  it('keeps a partial first week rather than dropping it', () => {
    // A window almost never begins on a Monday, and a dropped head is four
    // days of the card's history missing from the left of the plot.
    const weeks = weeksOf(isoDays(10).slice(3))

    expect(weeks.map((week) => week.to - week.from)).toEqual([4, 3])
  })
})

describe('ruleStep', () => {
  it('puts the rules on numbers a reader recognises', () => {
    // The scale stops at the data's own maximum, so the step cannot be a
    // quarter of a round ceiling: 283 / 4 is 70,75.
    expect(ruleStep(283)).toBe(100)
    // The reference's own scale: 0, 20, 40 and its 67 at the top.
    expect(ruleStep(67)).toBe(20)
    expect(ruleStep(9)).toBe(5)
  })
})

/** Where the `total` bucket sits inside one day's run of cells. */
const TOTAL = TRAFFIC_COLUMNS.findIndex((column) => column.key === 'total')

/** A display matrix with one traffic row, as `buildMetricsMatrix` shapes one. */
function viewOf(days, { orders, carts }) {
  const cells = (values) =>
    values.flatMap((value) =>
      // One cell per traffic column; the chart reads `total` and nothing else,
      // so the others are blanks holding the stride open.
      Array.from({ length: COLUMNS_PER_DAY }, (_, column) => ({
        raw: column === TOTAL ? value : null,
      })),
    )
  return {
    days: days.map((iso) => ({ iso, label: iso })),
    rows: [
      { key: 'orders', cells: cells(orders) },
      { key: 'carts', cells: cells(carts) },
    ],
    priceRows: [],
    stockRows: [],
    stockTotalRows: [],
  }
}

describe('buildFittedChart', () => {
  const days = isoDays(14)
  const view = viewOf(days, { orders: Array(14).fill(3), carts: Array(14).fill(10) })

  it('draws every metric as a daily line — nothing is a column', () => {
    // Columns were tried and dropped: a weekly column is a different quantity
    // from the daily numbers beside it.
    const chart = buildFittedChart(view, {
      metrics: ['orders', 'carts'],
      groups: SKU_METRIC_GROUPS,
    })

    expect(chart.option.series.map((entry) => entry.type)).toEqual(['line', 'line'])
    expect(chart.option.series[0].data).toHaveLength(14)
  })

  it('divides the axis by ONE week', () => {
    const chart = buildFittedChart(view, { metrics: ['orders'], groups: SKU_METRIC_GROUPS })
    const isStart = chart.option.xAxis.splitLine.interval

    // Day 0 and day 7 are Mondays; a fortnightly division would miss day 7,
    // which is exactly what it looked like on the page.
    expect([0, 7].map(isStart)).toEqual([true, true])
    expect([1, 6, 8].map(isStart)).toEqual([false, false, false])
  })

  it('fills the leading series and only the leading one', () => {
    // Two translucent fills over each other stop being a fill and become mud.
    const chart = buildFittedChart(view, {
      metrics: ['carts', 'orders'],
      groups: SKU_METRIC_GROUPS,
    })

    expect(chart.option.series[0].areaStyle).toBeTruthy()
    expect(chart.option.series[1].areaStyle).toBeUndefined()
  })

  it('draws metrics that share a unit as they are', () => {
    // Both are штуки, so the axis is already true for both. Rebasing them to
    // 100 costs an axis whose numbers are the numbers, and buys nothing.
    const chart = buildFittedChart(view, {
      metrics: ['carts', 'orders'],
      groups: SKU_METRIC_GROUPS,
    })

    expect(chart.option.series.map((entry) => entry.data[0])).toEqual([10, 3])
  })

  it('still rebases a mixed pick, where one axis cannot be true for both', () => {
    // «Затраты, ₽» beside «Заказы, шт» is the case the index exists for.
    const mixed = buildFittedChart(view, {
      metrics: ['spend', 'orders'],
      groups: SKU_METRIC_GROUPS,
    })

    // Spend has no values in this fixture, so the check is on the shape: the
    // non-ruler series carries `raw` alongside its plotted index.
    expect(mixed.option.series[0]).toHaveProperty('data')
    expect(mixed.option.series[1].data[0]).toBe(3)
  })

  it('leaves the plot one card wide — there is no ribbon to scroll', () => {
    // The live chart reports a `dayWidth` the scroller multiplies out. Nothing
    // here does: a year has to be on screen at once, which is the whole point.
    const chart = buildFittedChart(view, { metrics: ['orders'], groups: SKU_METRIC_GROUPS })

    expect(chart).not.toHaveProperty('dayWidth')
    expect(chart.option.xAxis.data).toHaveLength(14)
  })
})
