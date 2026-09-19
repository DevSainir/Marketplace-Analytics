import { describe, expect, it } from 'vitest'

import { buildFittedChart, foldWeekly, weeksOf } from '@/modules/labs/chartScaling'
import { SKU_METRIC_GROUPS } from '@/modules/labs/metricChart'
import { COLUMNS_PER_DAY, TRAFFIC_COLUMNS } from '@/modules/labs/metricsMatrix'

/**
 * The two long-window layouts (`chartScaling.js`).
 *
 * A sandbox, but the arithmetic under it is not decorative: a weekly fold that
 * sums остатки draws a warehouse holding seven times what it holds, and one
 * that indexes before folding rebases on a day instead of a week. Both are the
 * kind of wrong that looks plausible, so they are pinned here rather than
 * eyeballed on the page.
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

describe('foldWeekly', () => {
  const weeks = weeksOf(isoDays(14))

  it('sums a flow and parks it at the middle of its week', () => {
    const folded = foldWeekly(Array(14).fill(2), weeks, 'sum')

    expect(folded[weeks[0].mid]).toBe(14)
    expect(folded[weeks[1].mid]).toBe(14)
    // Everywhere else is null, not zero: one daily axis carries both the
    // weekly columns and the daily lines.
    expect(folded.filter((value) => value != null)).toHaveLength(2)
  })

  it('averages a level instead of summing it', () => {
    const folded = foldWeekly(Array(14).fill(700), weeks, 'avg')

    expect(folded[weeks[0].mid]).toBe(700)
  })

  it('leaves a week nobody reported as null', () => {
    const values = Array(14).fill(null)
    values[8] = 5

    const folded = foldWeekly(values, weeks, 'sum')

    expect(folded[weeks[0].mid]).toBeNull()
    expect(folded[weeks[1].mid]).toBe(5)
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

  it('folds the columns into weeks in «weekly-bars»', () => {
    const chart = buildFittedChart(view, {
      metrics: ['orders'],
      groups: SKU_METRIC_GROUPS,
      mode: 'weekly-bars',
    })

    const drawn = chart.option.series[0].data.filter((value) => value != null)
    expect(drawn).toEqual([21, 21])
  })

  it('draws every column as a daily line in «lines»', () => {
    const chart = buildFittedChart(view, {
      metrics: ['orders'],
      groups: SKU_METRIC_GROUPS,
      mode: 'lines',
    })

    expect(chart.option.series[0].type).toBe('line')
    expect(chart.option.series[0].data).toHaveLength(14)
  })

  it('leaves the plot one card wide — there is no ribbon to scroll', () => {
    // The live chart reports a `dayWidth` the scroller multiplies out. Nothing
    // here does: a year has to be on screen at once, which is the whole point.
    const chart = buildFittedChart(view, {
      metrics: ['orders', 'carts'],
      groups: SKU_METRIC_GROUPS,
      mode: 'weekly-bars',
    })

    expect(chart).not.toHaveProperty('dayWidth')
    expect(chart.option.xAxis.data).toHaveLength(14)
  })
})
