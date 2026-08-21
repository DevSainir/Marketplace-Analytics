import { SERIES_COLORS } from '@/modules/monitoring/chartOptions'
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
    // relationship. Small multiples are the allowed shape — several plots, one
    // axis each — so the rule is one y-axis PER GRID, not one per chart.
    for (const chart of buildChartSpecs(matrixView([]))) {
      const axes = [chart.option.yAxis].flat()
      const grids = axes.map((axis) => axis.gridIndex ?? 0)

      expect(new Set(grids).size).toBe(axes.length)
    }
  })

  it('gives the funnel a panel per series, each captioned', () => {
    // Клики run in the thousands and заказы in the tens: on one scale the
    // bottom two lie flat against the axis.
    const funnel = buildChartSpecs(matrixView([])).find((chart) => chart.key === 'funnel')

    expect(funnel.option.grid).toHaveLength(3)
    expect(funnel.option.yAxis.map((axis) => axis.name)).toEqual(['Клики', 'Корзины', 'Заказы'])
  })

  it('leaves headroom above the tallest mark, and none below zero', () => {
    // «Цена» and «Остатки» both peaked flush against the top edge, where a line
    // reads as clipped rather than as a maximum. The padding is top-only: a
    // bottom gap sent «ДРР», which cannot go negative, down to a −2% gridline.
    for (const chart of buildChartSpecs(matrixView([]))) {
      for (const axis of [chart.option.yAxis].flat()) {
        expect(axis.boundaryGap).toEqual([0, '12%'])
      }
    }
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
