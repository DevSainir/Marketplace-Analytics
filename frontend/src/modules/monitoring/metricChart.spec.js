import { METRIC_COLORS } from '@/modules/monitoring/chartOptions'
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
const chartOf = (metrics, rows = [], hover) =>
  buildMetricChart(matrixView(rows), { metrics, groups: SKU_METRIC_GROUPS, hover })

const seriesNamed = (chart, name) => chart.option.series.find((entry) => entry.name === name)
const axisOf = (chart) => [chart.option.yAxis].flat()[0]

/** One hovered point, as ECharts hands it to an axis-trigger formatter. */
const point = (seriesIndex, seriesName, value, dataIndex = 1) => ({
  seriesIndex,
  dataIndex,
  seriesName,
  value,
  marker: '',
  axisValue: '02.07',
})

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
      const chart = chartOf(['spend'], [row('spend', { total: [10, 20, 30] })])

      // Rebased to 100 at the first day: 10, 20, 30 is «doubled, then tripled».
      expect(seriesNamed(chart, 'Затраты, ₽').data).toEqual([100, 200, 300])
    })

    it('reads CPM out of the day\u2019s «Общая» column', () => {
      // The backend serves it there as the day's whole ad bill over the показы
      // it bought; the chart is a lookup, so this is what breaks if the row
      // ever goes back to being blank.
      const chart = chartOf(['cpm'], [row('cpm', { total: [150, 300, 225] })])

      expect(seriesNamed(chart, 'CPM, \u20bd').data).toEqual([100, 200, 150])
    })

    it('reads a mini-block metric off its one-cell-per-day row', () => {
      // «Цены» and «Остатки» are not day × bucket grids: each row already
      // carries a single «Общая» cell per day, so the stride must not apply.
      const chart = chartOf(['customer_price'], [row('customer_price', { total: [990, 890, 890] })])

      expect(seriesNamed(chart, 'Цена покупателя, ₽').data).toEqual([100, 89.9, 89.9])
    })

    it('renders a day WB served nothing as a gap, not as a zero', () => {
      // A blank day and a zero day mean different things, and joining the line
      // across the blank would draw a trend that never happened.
      const chart = chartOf(['spend'], [row('spend', { total: [5, null, 7] })])

      expect(seriesNamed(chart, 'Затраты, ₽').data[1]).toBeNull()
      expect(chart.option.series[0].connectNulls).toBe(false)
    })

    it('ignores a metric the catalogue does not hold', () => {
      // The account-wide page offers a shorter list; a key from the other one
      // must drop out rather than produce a phantom empty series.
      const chart = chartOf(['spend', 'нет-такого'], [row('spend', { total: [1, 2, 3] })])

      expect(chart.option.series.map((entry) => entry.name)).toEqual(['Затраты, ₽'])
    })
  })

  describe('everything is an index', () => {
    it('rebases each series to 100 at its first reported day', () => {
      // The answer to metrics whose scales do not fit together: «Заказы, ₽» at
      // 500 000 and «Затраты, ₽» at 7 000 share a unit and would share an axis,
      // which flattens the smaller one. Indexed, both are shapes.
      const chart = chartOf(['spend'], [row('spend', { total: [200, 400, 100] })])

      expect(seriesNamed(chart, 'Затраты, ₽').data).toEqual([100, 200, 50])
    })

    it('takes the baseline from the first day that reported, not from day one', () => {
      // A window often opens on blank days; rebasing against nothing would drop
      // the series entirely.
      const chart = chartOf(['spend'], [row('spend', { total: [null, 50, 100] })])

      expect(seriesNamed(chart, 'Затраты, ₽').data).toEqual([null, 100, 200])
    })

    it('leaves an all-blank series alone rather than dividing by nothing', () => {
      const chart = chartOf(['spend'], [row('spend', { total: [null, null, null] })])

      expect(seriesNamed(chart, 'Затраты, ₽').data).toEqual([null, null, null])
    })

    it('draws заказы unrebased, so they land on the ruler that measures them', () => {
      // The whole point of anchoring the scale to заказы: 120 заказов sits a
      // little above the 120 gridline. Indexed, it would sit at 100 and the
      // numbers down the left would mean nothing.
      const chart = chartOf(['orders'], [row('orders', { total: [100, 120, 90] })])

      expect(seriesNamed(chart, 'Заказы, шт').data).toEqual([100, 120, 90])
    })

    it('leaves every other metric a shape around 100', () => {
      // «Not affected at all»: заказы being real does not make затраты real,
      // because roubles on a scale of заказов would be a number in the wrong
      // units sitting on a real gridline.
      const chart = chartOf(
        ['spend', 'orders'],
        [row('spend', { total: [4000, 8000, 2000] }), row('orders', { total: [100, 120, 90] })],
      )

      expect(seriesNamed(chart, 'Затраты, ₽').data).toEqual([100, 200, 50])
      expect(seriesNamed(chart, 'Заказы, шт').data).toEqual([100, 120, 90])
    })

    it('puts every metric on one axis, whatever it measures', () => {
      const chart = chartOf(['spend', 'orders', 'order_conversion'])

      expect([chart.option.yAxis].flat()).toHaveLength(1)
      expect(chart.option.series.every((entry) => entry.yAxisIndex === undefined)).toBe(true)
    })
  })

  describe('the left-hand ruler', () => {
    it('is a scale of заказов, read from the window rather than from the picks', () => {
      // The marks are indices, so no scale can be true for all of them. It is
      // anchored to the one quantity the page is about instead — and ticking a
      // metric must not move it under the others.
      const rows = [row('orders', { total: [400, 430, 420] })]

      const withOrders = chartOf(['orders', 'spend'], rows)
      const withoutOrders = chartOf(['spend'], rows)

      expect(axisOf(withOrders).max).toBe(450)
      expect(axisOf(withoutOrders).max).toBe(450)
    })

    it('starts at zero and carries no unit name', () => {
      // The numbers are заказы and the marks are shapes; naming the axis «шт»
      // would claim the shapes were counts too.
      const chart = chartOf(['spend'], [row('orders', { total: [10, 20, 30] })])

      expect(axisOf(chart).min).toBe(0)
      expect(axisOf(chart).name).toBeUndefined()
    })

    it('falls back to a round ceiling when the window reports no заказы', () => {
      expect(axisOf(chartOf(['spend'], [row('spend', { total: [1, 2, 3] })])).max).toBe(500)
    })

    it('rises rather than cutting a series off the top of the plot', () => {
      // «Затраты» tripled indexes at 300; a ruler stopping at the day's 8
      // заказов would draw a line that simply stops, which is a lie.
      const chart = chartOf(
        ['spend'],
        [row('spend', { total: [100, 300, 100] }), row('orders', { total: [8, 8, 8] })],
      )

      expect(axisOf(chart).max).toBeGreaterThanOrEqual(300)
    })

    it('keeps the frozen column one axis wide, whatever was picked', () => {
      expect(chartOf(['spend', 'orders', 'order_conversion']).axisGutter).toBe(
        chartOf(['spend']).axisGutter,
      )
    })
  })

  describe('the order metrics are drawn in', () => {
    it('follows the catalogue, not the order the chips were clicked', () => {
      // The pick order used to reach the plot, so the same three metrics gave a
      // different legend, a different hover and different column positions on
      // every visit.
      const forwards = chartOf(['spend', 'carts', 'orders'])
      const backwards = chartOf(['orders', 'carts', 'spend'])

      expect(backwards.option.series.map((entry) => entry.name)).toEqual(
        forwards.option.series.map((entry) => entry.name),
      )
      expect(forwards.option.series.map((entry) => entry.name)).toEqual([
        'Затраты, ₽',
        'Корзины, шт',
        'Заказы, шт',
      ])
    })

    it('offers CPM straight after CTR, on both catalogues', () => {
      // The order is the legend's and the hover's too, so a metric's place in
      // the list is where a reader will keep finding it.
      const advertising = (groups) => groups[0].items.map((item) => item.key)

      expect(advertising(SKU_METRIC_GROUPS)).toEqual([
        'spend',
        'views',
        'clicks',
        'ctr',
        'cpm',
        'cpc',
        'drr_orders',
        'drr_sales',
      ])
      // CTR cannot follow to the account-wide page — «Клики» there is the
      // funnel's card opens, not advertising clicks — so CPM takes its place.
      expect(advertising(AGGREGATE_METRIC_GROUPS)).toEqual([
        'spend',
        'views',
        'clicks',
        'cpm',
        'drr_orders',
      ])
    })

    it('stands the columns of a day as корзины, заказы, остатки', () => {
      // Columns are drawn in series order, so this is what a reader sees left
      // to right inside every day.
      const chart = chartOf(['stock_quantity', 'orders', 'carts'])

      expect(chart.option.series.map((entry) => entry.name)).toEqual([
        'Корзины, шт',
        'Заказы, шт',
        'Остатки на складах, шт',
      ])
    })
  })

  describe('colour', () => {
    it('gives a metric the same hue however it was picked', () => {
      // Colour by slot made «Заказы» blue on one reading of the page and orange
      // on the next, so the legend had to be re-read every time.
      const first = chartOf(['orders', 'spend'])
      const second = chartOf(['spend', 'ctr', 'orders'])

      expect(seriesNamed(first, 'Заказы, шт').color).toBe(seriesNamed(second, 'Заказы, шт').color)
      expect(seriesNamed(first, 'Затраты, ₽').color).toBe(seriesNamed(second, 'Затраты, ₽').color)
    })

    it('gives every metric of a catalogue its own hue', () => {
      const keys = SKU_METRIC_GROUPS.flatMap((group) => group.items.map((item) => item.key))
      const hues = keys.map((key) => METRIC_COLORS[key])

      expect(new Set(hues).size).toBe(keys.length)
    })

    it('paints затраты and остатки green, корзины blue and заказы orange', () => {
      // The four the reader asked for by name, pinned so a palette edit cannot
      // quietly swap them.
      const chart = chartOf(['spend', 'carts', 'orders', 'stock_quantity'])
      const hue = (name) => seriesNamed(chart, name).color

      expect(hue('Затраты, ₽')).toBe('#1BAF7A')
      expect(hue('Остатки на складах, шт')).toBe('#0B7A3B')
      expect(hue('Корзины, шт')).toBe('#2A78D6')
      expect(hue('Заказы, шт')).toBe('#EB6834')
    })
  })

  describe('the hover', () => {
    const hoverOf = (chart, points) => chart.option.tooltip.formatter(points)

    it('shows the real value, and only that', () => {
      // An index is a shape, not a quantity: a reader who wants to know what
      // «200» meant in roubles must not have to leave the chart to find out.
      // The index itself is already on the canvas.
      const chart = chartOf(['spend'], [row('spend', { total: [200, 400, 100] })])

      const hover = hoverOf(chart, [point(0, 'Затраты, ₽', 200)])

      expect(hover).toContain('400') // the roubles actually spent that day
      expect(hover).not.toContain('(200)') // not the index it plots at
    })

    it('prints заказы as the count they already are', () => {
      // The plotted number IS the count here — nothing to translate back.
      const chart = chartOf(['orders'], [row('orders', { total: [100, 120, 90] })])

      const hover = hoverOf(chart, [point(0, 'Заказы, шт', 120)])

      expect(hover).toContain('120')
    })

    it('splits the rows into the groups the picker uses', () => {
      // Six unlike numbers in a flat list are read by hunting; «Реклама» and
      // «Воронка» are where the reader already looks for a metric.
      const chart = chartOf(['spend', 'carts'])

      const hover = hoverOf(chart, [point(0, 'Затраты, ₽', 100), point(1, 'Корзины, шт', 100)])

      expect(hover).toContain('Реклама')
      expect(hover).toContain('Воронка')
      expect(hover).toContain('dotted') // the rule between the two groups
    })

    it('answers a hover over the day with every metric on the plot', () => {
      const chart = chartOf(['spend', 'carts'], [], { index: null })

      const hover = hoverOf(chart, [point(0, 'Затраты, ₽', 100), point(1, 'Корзины, шт', 140)])

      expect(hover).toContain('Затраты, ₽')
      expect(hover).toContain('Корзины, шт')
    })

    it('answers a hover on one line with that metric alone', () => {
      // The reader pointed at a line; answering with five other metrics leaves
      // them doing the filtering the chart could have done.
      const cursor = { index: 1 }
      const chart = chartOf(['spend', 'carts'], [], cursor)

      const hover = hoverOf(chart, [point(0, 'Затраты, ₽', 100), point(1, 'Корзины, шт', 140)])

      expect(hover).toContain('Корзины, шт')
      expect(hover).not.toContain('Затраты, ₽')
    })

    it('shows both metrics where two of them cross', () => {
      // At a crossing there is no telling which line was aimed at, so narrowing
      // to one would be a guess.
      const chart = chartOf(['spend', 'carts'], [], { index: 1 })

      const hover = hoverOf(chart, [point(0, 'Затраты, ₽', 140), point(1, 'Корзины, шт', 140)])

      expect(hover).toContain('Корзины, шт')
      expect(hover).toContain('Затраты, ₽')
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

    it('lets a whole line answer a hover, not just its twenty dots', () => {
      // What makes «hover this metric» a line-sized target instead of a 5px
      // one: ECharts fires no event for the path between symbols unless asked.
      const chart = chartOf(['spend'])

      expect(chart.option.series[0].triggerLineEvent).toBe(true)
    })

    it('draws rates, prices and ratios as lines', () => {
      const chart = chartOf(['spend', 'customer_price', 'order_conversion'])

      expect(chart.option.series.every((entry) => entry.type === 'line')).toBe(true)
    })
  })

  describe('what the component renders around the plot', () => {
    it('names and colours the legend to match the series', () => {
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

    it('changes its key when the question changes, so the ribbon re-pins', () => {
      // The ribbon jumps back to the newest days on a new key. A pick is a new
      // question about how things are NOW, so it must not be answered a
      // fortnight back, wherever the reader happened to leave the scroll.
      expect(chartOf(['spend', 'orders']).key).not.toBe(chartOf(['spend']).key)
      expect(chartOf(['spend']).key).toBe(chartOf(['spend']).key)
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

  describe('a long window', () => {
    /** The same chart over `count` days — the window, not the picks, is the input. */
    const over = (count) =>
      buildMetricChart(
        buildMetricsMatrix({
          nm_id: 1,
          matrix: {
            days: Array.from({ length: count }, (_, i) => `2026-0${1 + Math.floor(i / 28)}-01`),
            buckets: TRAFFIC_COLUMNS.map((column) => column.key),
            rows: [],
          },
        }),
        { metrics: ['orders'], groups: SKU_METRIC_GROUPS },
      )

    it('draws its days closer together, so more of them fit the card', () => {
      // Past two months the reader is after a trend, not Tuesday against
      // Wednesday — and a quarter at the full width is six screens of ribbon.
      expect(over(60).dayWidth).toBeLessThan(over(59).dayWidth)
    })

    it('keeps the full width right up to the threshold', () => {
      // One step, not a curve: a width that slid with the day count would
      // rescale the whole plot every time the calendar moved by a day.
      expect(over(30).dayWidth).toBe(over(59).dayWidth)
      expect(over(60).dayWidth).toBe(over(90).dayWidth)
    })

    it('thins the columns with it, so days stay visibly apart', () => {
      // Three 28px columns in a 44px day would touch their neighbours and the
      // day boundaries would stop reading.
      const width = (chart) => chart.option.series[0].barMaxWidth

      expect(width(over(60))).toBeLessThan(width(over(59)))
      expect(width(over(60))).toBeLessThan(over(60).dayWidth / 2)
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
