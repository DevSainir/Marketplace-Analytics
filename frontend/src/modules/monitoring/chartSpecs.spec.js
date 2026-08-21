import { SERIES_COLORS, axisOnlyOption, plotOnlyOption } from '@/modules/monitoring/chartOptions'
import { buildChartSpecs } from '@/modules/monitoring/chartSpecs'
import {
  COLUMNS_PER_DAY,
  TRAFFIC_COLUMNS,
  buildMetricsMatrix,
} from '@/modules/monitoring/metricsMatrix'

const DAYS = ['2026-07-01', '2026-07-02']

/** A backend matrix row: flat, day-major, `COLUMNS_PER_DAY` cells per day. */
function row(key, valuesByBucket) {
  const values = DAYS.flatMap((_, day) =>
    TRAFFIC_COLUMNS.map((column) => valuesByBucket[column.key]?.[day] ?? null),
  )
  return { key, values }
}

/** The display matrix the store hands the panel, built the way the store does. */
function matrixView(rows) {
  return buildMetricsMatrix({
    nm_id: 1,
    matrix: { days: DAYS, buckets: TRAFFIC_COLUMNS.map((c) => c.key), rows },
  })
}

describe('buildChartSpecs', () => {
  it('has no slides at all without a window', () => {
    expect(buildChartSpecs({ days: [], rows: [] })).toEqual([])
    expect(buildChartSpecs(null)).toEqual([])
  })

  it('reads a «Общая» metric off the matrix into the day series', () => {
    const view = matrixView([row('order_sum', { total: [1000, 2500] })])

    const sales = buildChartSpecs(view).find((chart) => chart.key === 'sales')
    const orders = sales.option.series.find((s) => s.name === 'Заказы, ₽')

    expect(orders.data).toEqual([1000, 2500])
    expect(sales.empty).toBe(false)
  })

  it('reads each advertising bucket into its own stacked series', () => {
    const view = matrixView([row('spend', { uni_search: [10, 20], cpc_shelves: [3, 4] })])

    const spend = buildChartSpecs(view).find((chart) => chart.key === 'spend_mix')
    const byName = new Map(spend.option.series.map((s) => [s.name, s]))

    expect(byName.get('Единая · поиск').data).toEqual([10, 20])
    expect(byName.get('CPC · полки').data).toEqual([3, 4])
    // Stacking is ECharts' job — the frontend never sums the buckets itself.
    expect(spend.option.series.every((s) => s.stack === 'spend')).toBe(true)
  })

  it('keeps «Органика» out of the spend chart and in the orders chart', () => {
    const charts = buildChartSpecs(matrixView([row('orders', { organic: [5, 6] })]))
    const names = (key) =>
      charts.find((chart) => chart.key === key).option.series.map((s) => s.name)

    expect(names('spend_mix')).not.toContain('Органика')
    expect(names('orders_mix')).toContain('Органика')
  })

  it('drops the always-empty «Каталог» zone of the unified campaigns', () => {
    // `uni_catalog` is a legacy WB zone that no longer exists in the v2 API; a
    // series for it would be a permanently blank legend entry.
    const charts = buildChartSpecs(matrixView([row('spend', {})]))
    const spend = charts.find((chart) => chart.key === 'spend_mix')

    expect(spend.option.series).toHaveLength(7)
  })

  it('never asks for a ninth categorical colour', () => {
    // Past eight, a slot would be recycled and two series would share a hue.
    const charts = buildChartSpecs(matrixView([]))

    for (const chart of charts) {
      expect(chart.option.series.length).toBeLessThanOrEqual(SERIES_COLORS.length)
      expect(new Set(chart.option.series.map((s) => s.color)).size).toBe(chart.option.series.length)
    }
  })

  it('never puts two y-axes on one plot', () => {
    // Two scales behind one set of marks make any crossing look like a
    // relationship, and worse — three scales put клики 439, корзины 215 and
    // заказы 105 on the SAME point of the plot, which is the opposite of the
    // absolute reading a funnel needs. Small multiples are the allowed shape
    // for series of different magnitude («Воронка 2»): several plots, one axis
    // each. So the rule is one y-axis PER GRID.
    for (const chart of buildChartSpecs(matrixView([]))) {
      const axes = [chart.option.yAxis].flat()
      const grids = axes.map((axis) => axis.gridIndex ?? 0)

      expect(new Set(grids).size).toBe(axes.length)
    }
  })

  it('draws the two «Воронка» tabs from one set of series', () => {
    // The same three numbers, two ways of looking at them: one plot with a
    // hidden scale per line, and one panel per line with a plain axis.
    const charts = buildChartSpecs(matrixView([]))
    const one = charts.find((chart) => chart.key === 'funnel')
    const two = charts.find((chart) => chart.key === 'funnel_panels')

    expect([one.tab, two.tab]).toEqual(['Воронка 1', 'Воронка 2'])
    expect(one.option.series.map((entry) => entry.name)).toEqual(
      two.option.series.map((entry) => entry.name),
    )
    expect(one.option.series.map((entry) => entry.data)).toEqual(
      two.option.series.map((entry) => entry.data),
    )
  })

  it('plots «Воронка 1» on ONE absolute scale', () => {
    // One axis, three lines measured against it: заказы run low and flat under
    // клики, which is the truth about a funnel. Given a scale each they were
    // each stretched to the full plot height, so a day with 439 clicks, 215
    // carts and 105 orders drew all three at the same point — a chart that
    // contradicted its own tooltip.
    const one = buildChartSpecs(matrixView([])).find((chart) => chart.key === 'funnel')

    expect(Array.isArray(one.option.yAxis)).toBe(false)
    expect(one.option.series).toHaveLength(3)
    expect(one.option.series.every((entry) => entry.yAxisIndex === undefined)).toBe(true)
  })

  it('captions every «Воронка 2» panel on its own visible axis', () => {
    const two = buildChartSpecs(matrixView([])).find((chart) => chart.key === 'funnel_panels')

    expect(two.option.grid).toHaveLength(3)
    expect(two.option.yAxis.map((axis) => axis.name)).toEqual(['Клики', 'Корзины', 'Заказы'])
    expect(two.axisGutter).toBeGreaterThan(0)
  })

  it('leaves headroom above the tallest mark, by whichever means the axis allows', () => {
    // «Цена» and «Остатки» both peaked flush against the top edge, where a line
    // reads as clipped rather than as a maximum. The two mechanisms exclude
    // each other: ANY `boundaryGap` on a value axis re-anchors it to zero, so
    // only a zero-anchored axis can use one. A scaled axis gets its head-room
    // from `scale`'s own rounding up to the next whole tick — and keeping
    // `boundaryGap` off it is what lets the funnel fit its band instead of
    // starting at zero.
    for (const chart of buildChartSpecs(matrixView([]))) {
      for (const axis of [chart.option.yAxis].flat()) {
        if (axis.scale) expect(axis.boundaryGap).toBeUndefined()
        else expect(axis.boundaryGap).toEqual(['0%', '12%'])
      }
    }
  })

  it('reports the day count the ribbon is sized from', () => {
    // The plot is laid out at a fixed width PER DAY and scrolled sideways, the
    // way the metrics table's ribbon is — so the panel has to know how many.
    for (const chart of buildChartSpecs(matrixView([]))) {
      expect(chart.dayCount).toBe(DAYS.length)
    }
  })

  it('names and colours the legend for the panel to render in HTML', () => {
    // On the canvas the legend scrolled away with the days it labels.
    const sales = buildChartSpecs(matrixView([])).find((chart) => chart.key === 'sales')

    expect(sales.legend.map((entry) => entry.name)).toEqual(['Заказы, ₽', 'Выкупы, ₽'])
    expect(sales.legend.map((entry) => entry.color)).toEqual(SERIES_COLORS.slice(0, 2))
    // ...and it is gone from the option, or it would be drawn twice.
    expect(sales.option.legend).toBeUndefined()
  })

  it('splits into a pinned axis and a scrolling plot that agree', () => {
    // Both copies keep the same series and the same axis config, which is what
    // makes ECharts land on identical ticks without any extent maths here.
    const sales = buildChartSpecs(matrixView([row('order_sum', { total: [1000, 2500] })])).find(
      (chart) => chart.key === 'sales',
    )
    const axis = axisOnlyOption(sales.option)
    const plot = plotOnlyOption(sales.option)

    expect(axis.series.map((entry) => entry.data)).toEqual(plot.series.map((entry) => entry.data))
    expect(axis.yAxis.scale).toBe(plot.yAxis.scale)
    expect(axis.yAxis.axisLabel.show).not.toBe(false) // the pinned copy shows them
    expect(plot.yAxis.axisLabel.show).toBe(false) // the scrolling one does not
    expect(axis.series.every((entry) => entry.silent)).toBe(true)
  })

  it('anchors bars and stacks to zero, and lets a plain line chart zoom', () => {
    // A price band of 990–1290 ₽ pinned to zero spends four fifths of the plot
    // on empty space; a bar's length, and a stack's sum, mean nothing without
    // the zero baseline.
    const charts = buildChartSpecs(matrixView([]))
    const scaled = (key) => charts.find((chart) => chart.key === key).option.yAxis.scale

    expect(scaled('sales')).toBe(false)
    expect(scaled('stock')).toBe(false)
    expect(scaled('orders_mix')).toBe(false)
    expect(scaled('price')).toBe(true)
    expect(scaled('drr')).toBe(true)
  })

  it('flags a slide whose every series is blank, and keeps its tab', () => {
    const charts = buildChartSpecs(matrixView([row('order_sum', { total: [null, null] })]))

    expect(charts.find((chart) => chart.key === 'sales').empty).toBe(true)
    expect(charts.map((chart) => chart.key)).toContain('sales')
  })

  it('reads price and stock off their «Общая»-only mini blocks', () => {
    const view = matrixView([
      row('customer_price', { total: [990, 890] }),
      row('stock_quantity', { total: [40, 31] }),
    ])
    const charts = buildChartSpecs(view)
    const series = (key, name) =>
      charts.find((chart) => chart.key === key).option.series.find((s) => s.name === name)

    expect(series('price', 'Цена покупателя, ₽').data).toEqual([990, 890])
    expect(series('stock', 'На складах').data).toEqual([40, 31])
  })

  it('labels the x axis by day, shortened to fit a 30-column window', () => {
    const charts = buildChartSpecs(matrixView([]))

    expect(charts[0].option.xAxis.data).toEqual(['01.07', '02.07'])
  })

  it('follows the matrix stride when reading a bucket other than the first', () => {
    // A day section is COLUMNS_PER_DAY wide; reading with the wrong stride
    // silently returns another bucket's number, which still renders.
    const view = matrixView([row('clicks', { organic: [7, 9] })])
    const clicksRow = view.rows.find((r) => r.key === 'clicks')
    const organicColumn = TRAFFIC_COLUMNS.findIndex((c) => c.key === 'organic')

    expect(clicksRow.cells[COLUMNS_PER_DAY + organicColumn].raw).toBe(9)
    expect(
      buildChartSpecs(view)
        .find((chart) => chart.key === 'orders_mix')
        .option.series.find((s) => s.name === 'Органика').data,
    ).toEqual([null, null])
  })
})
