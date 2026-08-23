import {
  AGGREGATE_METRIC_GROUPS,
  SKU_METRIC_GROUPS,
  buildMetricChart,
} from '@/modules/monitoring/metricChart'
import { TRAFFIC_COLUMNS, buildMetricsMatrix } from '@/modules/monitoring/metricsMatrix'

const DAYS = ['2026-07-01', '2026-07-02', '2026-07-03']

/** A backend matrix row: flat, day-major, `COLUMNS_PER_DAY` cells per day. */
function row(key, valuesByBucket) {
  const values = DAYS.flatMap((_, day) =>
    TRAFFIC_COLUMNS.map((column) => valuesByBucket[column.key]?.[day] ?? null),
  )
  return { key, values }
}

/**
 * The display matrix the store hands the chart, built the way the store builds
 * it — the real mapping code rather than a hand-written shape that can drift
 * from it.
 */
function matrixView(rows = []) {
  return buildMetricsMatrix({
    nm_id: 1,
    matrix: { days: DAYS, buckets: TRAFFIC_COLUMNS.map((column) => column.key), rows },
  })
}

/** Build with the per-SKU catalogue, which is what both pages' chart uses. */
const chartOf = (metrics, rows = [], mode = 'absolute') =>
  buildMetricChart(matrixView(rows), { metrics, groups: SKU_METRIC_GROUPS, mode })

const seriesNamed = (chart, name) => chart.option.series.find((entry) => entry.name === name)
const axesOf = (chart) => [chart.option.yAxis].flat()

describe('buildMetricChart', () => {
  it('draws nothing at all when the window has no days', () => {
    // The page renders the block only when there is something in it; a chart
    // over an empty window would be an axis around nothing.
    expect(buildMetricChart({ days: [], rows: [] }, { groups: SKU_METRIC_GROUPS })).toBeNull()
    expect(buildMetricChart(null, { groups: SKU_METRIC_GROUPS })).toBeNull()
  })

  describe('reading the matrix', () => {
    it('follows the day-major stride when reading a bucket', () => {
      // A day section is COLUMNS_PER_DAY wide. Reading with the wrong stride
      // returns some other bucket's number, which renders perfectly happily —
      // so this pins the arithmetic rather than the absence of a crash.
      const view = matrixView([row('spend', { total: [10, 20, 30], uni_search: [1, 2, 3] })])

      const chart = buildMetricChart(view, { metrics: ['spend'], groups: SKU_METRIC_GROUPS })

      expect(seriesNamed(chart, 'Затраты, ₽').data).toEqual([10, 20, 30])
    })

    it('reads a mini-block metric off its one-cell-per-day row', () => {
      // «Цены» and «Остатки» are not day × bucket grids: each row already
      // carries a single «Общая» cell per day, so the stride must not apply.
      const chart = chartOf(['customer_price'], [row('customer_price', { total: [990, 890, 890] })])

      expect(seriesNamed(chart, 'Цена покупателя, ₽').data).toEqual([990, 890, 890])
    })

    it('renders a day WB served nothing as a gap, not as a zero', () => {
      // A blank day and a zero day mean different things, and joining the line
      // across the blank would draw a trend that never happened.
      const chart = chartOf(['spend'], [row('spend', { total: [5, null, 7] })])

      expect(seriesNamed(chart, 'Затраты, ₽').data).toEqual([5, null, 7])
      expect(chart.option.series[0].connectNulls).toBe(false)
    })

    it('ignores a metric the catalogue does not hold', () => {
      // The account-wide page offers a shorter list; a key from the other one
      // must drop out rather than produce a phantom empty series.
      const chart = chartOf(['spend', 'нет-такого'], [row('spend', { total: [1, 2, 3] })])

      expect(chart.option.series.map((entry) => entry.name)).toEqual(['Затраты, ₽'])
    })
  })

  describe('one axis per unit', () => {
    it('gives two metrics of the same unit one shared ruler', () => {
      // The rule the funnel taught: separate scales for корзины and заказы put
      // 215 and 105 on the same point of the plot.
      const chart = chartOf(['carts', 'orders'])

      expect(axesOf(chart)).toHaveLength(1)
      expect(chart.option.series.every((entry) => entry.yAxisIndex === 0)).toBe(true)
    })

    it('gives metrics of different units an axis each, named by the unit', () => {
      const chart = chartOf(['spend', 'orders', 'order_conversion'])

      expect(axesOf(chart).map((axis) => axis.name)).toEqual(['₽', 'шт', '%'])
      expect(chart.option.series.map((entry) => entry.yAxisIndex)).toEqual([0, 1, 2])
    })

    it('orders the axes ₽, шт, % whatever order they were picked in', () => {
      // Not first-appearance order: the same three metrics used to lay the
      // frozen column out differently depending on which chip was clicked first.
      const chart = chartOf(['order_conversion', 'orders', 'spend'])

      expect(axesOf(chart).map((axis) => axis.name)).toEqual(['₽', 'шт', '%'])
    })

    it('puts the first unit furthest from the plot, so the column reads ₽ шт %', () => {
      // A bigger offset pushes an axis further LEFT, so the order above is only
      // what a reader sees if the offsets run backwards.
      const chart = chartOf(['spend', 'orders', 'order_conversion'])

      const offsets = axesOf(chart).map((axis) => axis.offset)
      expect(offsets[0]).toBeGreaterThan(offsets[1])
      expect(offsets[1]).toBeGreaterThan(offsets[2])
    })

    it('anchors a unit carrying bars to zero and lets a line-only unit fit', () => {
      // A bar's length IS its value, so a cut baseline lies about it; a line may
      // fit its own band, which is what makes a flat ДРР readable.
      const chart = chartOf(['orders', 'drr_sales'])

      const [counts, percent] = axesOf(chart)
      expect(counts.scale).toBe(false) // «Заказы, шт» is drawn as columns
      expect(percent.scale).toBe(true)
    })
  })

  describe('the frozen column', () => {
    it('widens for each axis drawn', () => {
      const one = chartOf(['spend'])
      const three = chartOf(['spend', 'orders', 'order_conversion'])

      expect(three.axisGutter).toBeGreaterThan(one.axisGutter)
    })

    it('stays one column wide in index mode, however many units were picked', () => {
      // Index mode draws exactly one axis whatever the metrics measure. Sizing
      // the column per unit regardless left a gaping margin beside a single
      // «инд.» scale, and made the margin jump when a pick added a unit without
      // adding an axis.
      const absolute = chartOf(['spend', 'orders', 'order_conversion'])
      const indexed = chartOf(['spend', 'orders', 'order_conversion'], [], 'index')

      expect(indexed.axisGutter).toBe(chartOf(['spend']).axisGutter)
      expect(indexed.axisGutter).toBeLessThan(absolute.axisGutter)
    })
  })

  describe('index mode', () => {
    it('rebases each series to 100 at its first reported day', () => {
      // The answer to metrics whose scales do not fit together: «Заказы, ₽» at
      // 500 000 and «Затраты, ₽» at 7 000 share a unit and therefore an axis,
      // which flattens the smaller one. Indexed, both are shapes.
      const rows = [row('spend', { total: [200, 400, 100] })]

      const chart = chartOf(['spend'], rows, 'index')

      expect(seriesNamed(chart, 'Затраты, ₽').data).toEqual([100, 200, 50])
    })

    it('still shows the real value on hover, with the index beside it', () => {
      // An index is a shape, not a quantity: a reader who wants to know what
      // «200» meant in roubles must not have to leave the chart to find out.
      const chart = chartOf(['spend'], [row('spend', { total: [200, 400, 100] })], 'index')

      const hover = chart.option.tooltip.formatter([
        {
          seriesIndex: 0,
          dataIndex: 1,
          seriesName: 'Затраты, ₽',
          value: 200,
          marker: '',
          axisValue: '02.07',
        },
      ])

      expect(hover).toContain('400') // the roubles actually spent that day
      expect(hover).toContain('200') // and the index it plots at
    })

    it('shows only the value in absolute mode, with no index to add', () => {
      const chart = chartOf(['spend'], [row('spend', { total: [200, 400, 100] })])

      const hover = chart.option.tooltip.formatter([
        {
          seriesIndex: 0,
          dataIndex: 1,
          seriesName: 'Затраты, ₽',
          value: 400,
          marker: '',
          axisValue: '02.07',
        },
      ])

      expect(hover).toContain('400')
      expect(hover).not.toContain('(')
    })

    it('takes the baseline from the first day that reported, not from day one', () => {
      // A window often opens on blank days; rebasing against nothing would drop
      // the series entirely.
      const chart = chartOf(['spend'], [row('spend', { total: [null, 50, 100] })], 'index')

      expect(seriesNamed(chart, 'Затраты, ₽').data).toEqual([null, 100, 200])
    })

    it('leaves an all-blank series alone rather than dividing by nothing', () => {
      const chart = chartOf(['spend'], [row('spend', { total: [null, null, null] })], 'index')

      expect(seriesNamed(chart, 'Затраты, ₽').data).toEqual([null, null, null])
    })

    it('puts everything on one unitless axis', () => {
      const chart = chartOf(['spend', 'orders', 'order_conversion'], [], 'index')

      expect(axesOf(chart)).toHaveLength(1)
      expect(chart.option.series.every((entry) => entry.yAxisIndex === 0)).toBe(true)
    })
  })

  describe('marks', () => {
    it('draws остатки, корзины and заказы as columns standing side by side', () => {
      // Three separate counts, so they are never stacked: a stack would draw a
      // total in which a cart is a unit of stock.
      const chart = chartOf(['carts', 'orders', 'stock_quantity'])

      expect(chart.option.series.map((entry) => entry.type)).toEqual(['bar', 'bar', 'bar'])
      expect(chart.option.series.every((entry) => !entry.stack)).toBe(true)
    })

    it('draws rates, prices and ratios as lines', () => {
      const chart = chartOf(['spend', 'customer_price', 'order_conversion'])

      expect(chart.option.series.every((entry) => entry.type === 'line')).toBe(true)
    })
  })

  describe('what the component renders around the plot', () => {
    it('names and colours the legend to match the series, in pick order', () => {
      const chart = chartOf(['spend', 'orders'])

      expect(chart.legend.map((entry) => entry.name)).toEqual(
        chart.option.series.map((entry) => entry.name),
      )
      expect(chart.legend.map((entry) => entry.color)).toEqual(
        chart.option.series.map((entry) => entry.color),
      )
    })

    it('reports the day count the scrolling ribbon is sized from', () => {
      expect(chartOf(['spend']).dayCount).toBe(DAYS.length)
    })

    it('flags a selection whose every series is blank', () => {
      // So the component can say «нет данных» instead of drawing empty axes.
      expect(chartOf(['spend'], [row('spend', { total: [null, null, null] })]).empty).toBe(true)
      expect(chartOf(['spend'], [row('spend', { total: [1, 2, 3] })]).empty).toBe(false)
    })

    it('flags an empty selection as empty too', () => {
      expect(chartOf([]).empty).toBe(true)
    })
  })

  describe('the two catalogues', () => {
    it('offers only metrics an account-wide sum can honestly answer', () => {
      // Prices are per-card facts, CTR and CPC need one card's campaigns, and
      // «Процент выкупа» is a lagged cohort the aggregate endpoint does not
      // compute. Each is absent rather than approximated.
      const keys = AGGREGATE_METRIC_GROUPS.flatMap((group) => group.items.map((item) => item.key))

      expect(keys).not.toContain('seller_price')
      expect(keys).not.toContain('customer_price')
      expect(keys).not.toContain('ctr')
      expect(keys).not.toContain('cpc')
      expect(keys).not.toContain('buyout_percent')
    })

    it('resolves a selection against the catalogue it was handed', () => {
      const view = matrixView([row('order_sum', { total: [10, 20, 30] })])

      const aggregate = buildMetricChart(view, {
        metrics: ['order_sum'],
        groups: AGGREGATE_METRIC_GROUPS,
      })
      const sku = buildMetricChart(view, { metrics: ['order_sum'], groups: SKU_METRIC_GROUPS })

      expect(aggregate.option.series.map((entry) => entry.name)).toEqual(['Заказы, ₽'])
      expect(sku.option.series).toEqual([]) // the SKU catalogue has no such key
    })
  })
})
