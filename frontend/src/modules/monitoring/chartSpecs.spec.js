import { SERIES_COLORS, axisOnlyOption, plotOnlyOption } from '@/modules/monitoring/chartOptions'
import {
  DEFAULT_OVERVIEW,
  OVERVIEW_METRICS,
  buildChartSpecs,
} from '@/modules/monitoring/chartSpecs'
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

const chart = (key, rows = [], options) =>
  buildChartSpecs(matrixView(rows), options).find((entry) => entry.key === key)

describe('buildChartSpecs', () => {
  it('has no slides at all without a window', () => {
    expect(buildChartSpecs({ days: [], rows: [] })).toEqual([])
    expect(buildChartSpecs(null)).toEqual([])
  })

  it('reads a «Общая» metric off the matrix into the day series', () => {
    const sales = chart('sales', [row('order_sum', { total: [1000, 2500] })])

    expect(sales.option.series.find((s) => s.name === 'Заказы, ₽').data).toEqual([1000, 2500])
    expect(sales.empty).toBe(false)
  })

  it('reads each advertising bucket into its own stacked series', () => {
    const spend = chart('spend_mix', [row('spend', { uni_search: [10, 20], cpc_shelves: [3, 4] })])
    const byName = new Map(spend.option.series.map((s) => [s.name, s]))

    expect(byName.get('Единая · поиск').data).toEqual([10, 20])
    expect(byName.get('CPC · полки').data).toEqual([3, 4])
    // Stacking is ECharts' job — the frontend never sums the buckets itself.
    expect(spend.option.series.every((s) => s.stack === 'spend')).toBe(true)
  })

  it('drops the always-empty «Каталог» zone of the unified campaigns', () => {
    expect(chart('spend_mix').option.series).toHaveLength(7)
  })

  it('never asks for a ninth categorical colour', () => {
    // Past eight, a slot would be recycled and two series would share a hue.
    for (const entry of buildChartSpecs(matrixView([]))) {
      expect(entry.option.series.length).toBeLessThanOrEqual(SERIES_COLORS.length)
    }
  })

  describe('one axis per UNIT', () => {
    it('gives two metrics of the same unit one shared ruler', () => {
      // The rule the funnel taught: three scales for клики/корзины/заказы put
      // 439, 215 and 105 on the same point of the plot. Same unit, same axis.
      // «Остаток, шт» and «Заказы, шт» — one unit, therefore one axis, and
      // every series pinned to it.
      const stock = chart('stock')

      expect([stock.option.yAxis].flat()).toHaveLength(1)
      expect(stock.option.series.every((s) => s.yAxisIndex === 0)).toBe(true)
    })

    it('gives metrics of different units an axis each, named by the unit', () => {
      // «Затраты, ₽» and «ДРР, %» answer one question together and cannot share
      // a scale, so they get one axis apiece — labelled by unit, not by series,
      // because an axis measures everything on the chart denominated that way.
      const ads = chart('ads')
      const axes = [ads.option.yAxis].flat()

      // Затраты ₽ (bars) · Заказы шт (line) · ДРР % (line) — volume against
      // efficiency, which is the shape ad dashboards use.
      expect(axes.map((axis) => axis.name)).toEqual(['₽', 'шт', '%'])
      expect(ads.option.series.map((s) => s.yAxisIndex)).toEqual([0, 1, 2])
    })

    it('widens the frozen column for the second axis', () => {
      expect(chart('ads').axisGutter).toBeGreaterThan(chart('stock').axisGutter)
    })

    it('anchors a unit carrying bars to zero, and lets a line-only unit fit', () => {
      // A bar's length IS its value, so a cut baseline lies about it; a line
      // may fit its own band, which is what makes a flat ДРР readable.
      const axes = [chart('ads').option.yAxis].flat()

      expect(axes[0].scale).toBe(false) // ₽ carries the spend bars
      expect(axes[1].scale).toBe(true) // % carries only lines
    })
  })

  describe('«Общий»', () => {
    it('draws whatever the reader ticked, in the order they ticked it', () => {
      const overview = chart('overview', [], { overview: ['orders', 'spend'] })

      expect(overview.option.series.map((s) => s.name)).toEqual(['Заказы, шт', 'Затраты, ₽'])
    })

    it('opens on the money question rather than on nothing', () => {
      expect(chart('overview').option.series).toHaveLength(DEFAULT_OVERVIEW.length)
    })

    it('draws nothing at all when everything is unticked', () => {
      expect(chart('overview', [], { overview: [] }).option.series).toEqual([])
    })

    it('offers every metric it can actually resolve', () => {
      // A chip naming a metric the matrix cannot serve would tick and do
      // nothing, which reads as a broken control rather than an empty day.
      for (const choice of OVERVIEW_METRICS) {
        const only = chart('overview', [], { overview: [choice.key] })
        expect(only.option.series, choice.key).toHaveLength(1)
      }
    })

    it('stops at four series, because past that nobody can read it', () => {
      // Dashboard guidance puts the readable ceiling at four to six lines and
      // Google's own metric comparison shows two. Seventeen chips with no cap
      // let a reader build a hairball and blame the chart.
      const many = ['order_sum', 'spend', 'orders', 'clicks', 'carts', 'views']
      const overview = chart('overview', [], { overview: many })

      expect(overview.option.series).toHaveLength(4)
    })

    it('rebases every series to 100 in index mode, keeping the real values', () => {
      // The documented answer to unlike scales: «Заказы, ₽» at 500 000 and
      // «Затраты, ₽» at 7 000 share a unit and therefore an axis, which
      // flattens the smaller one. Indexed, both are shapes — and the hover
      // still reads the roubles, because an index is not a quantity.
      const rows = [row('order_sum', { total: [200, 400] }), row('spend', { total: [10, 5] })]
      const indexed = chart('overview', rows, {
        overview: ['order_sum', 'spend'],
        mode: 'index',
      })

      expect(indexed.option.series.map((s) => s.data)).toEqual([
        [100, 200],
        [100, 50],
      ])
      // One axis for everything: an index is unitless.
      expect([indexed.option.yAxis].flat()).toHaveLength(1)
    })

    it('leaves absolute mode alone, with an axis per unit', () => {
      const rows = [row('order_sum', { total: [200, 400] }), row('spend', { total: [10, 5] })]
      const absolute = chart('overview', rows, { overview: ['order_sum', 'spend'] })

      expect(absolute.option.series[0].data).toEqual([200, 400])
      expect([absolute.option.yAxis].flat()).toHaveLength(1) // both are ₽
    })

    it('is the only slide carrying a picker', () => {
      const pickable = buildChartSpecs(matrixView([])).filter((entry) => entry.pickable)

      expect(pickable.map((entry) => entry.key)).toEqual(['overview'])
    })
  })

  it('pairs metrics that explain each other rather than standing alone', () => {
    // The redesign's rule, from how ad dashboards are actually built: a lone
    // series is a number on a wall. «Цена» said nothing actionable by itself;
    // price against demand asks whether the last cut worked.
    const price = chart('price')

    expect(price.option.series.map((s) => s.name)).toEqual(
      expect.arrayContaining(['Цена покупателя, ₽', 'Заказы, шт']),
    )
    // ...and the slides that said nothing on their own are gone.
    const tabs = buildChartSpecs(matrixView([])).map((entry) => entry.tab)
    expect(tabs).not.toContain('Цены')
    expect(tabs).not.toContain('Остатки')
  })

  it('splits into a pinned axis and a scrolling plot that agree', () => {
    // Both copies keep the same series and the same axis config, which is what
    // makes ECharts land on identical ticks without any extent maths here.
    const sales = chart('sales', [row('order_sum', { total: [1000, 2500] })])
    const axis = axisOnlyOption(sales.option)
    const plot = plotOnlyOption(sales.option)

    expect(axis.series.map((e) => e.data)).toEqual(plot.series.map((e) => e.data))
    expect(axis.series.every((e) => e.silent)).toBe(true)
    expect([plot.yAxis].flat().every((a) => a.axisLabel.show === false)).toBe(true)
  })

  it('reports the day count the ribbon is sized from', () => {
    // Except the funnel, which is the window in one shape and has no ribbon.
    for (const entry of buildChartSpecs(matrixView([]))) {
      expect(entry.dayCount, entry.key).toBe(entry.funnel ? 0 : DAYS.length)
    }
  })

  describe('«Воронка»', () => {
    const TOTALS = {
      open_count: 1000,
      cart_count: 200,
      order_count: 50,
      buyout_count: 40,
      cart_conversion: 20,
      order_conversion: 25,
      buyout_conversion: 80,
    }

    it('draws the window as a funnel, not as five day-series', () => {
      // The old slide put three counts and two percentages over thirty days on
      // one plot and answered none of «where do we lose people».
      const funnel = chart('funnel', [], { totals: TOTALS })

      expect(funnel.funnel).toBe(true)
      expect(funnel.option.series[0].type).toBe('funnel')
      expect(funnel.option.series[0].data.map((stage) => stage.name)).toEqual([
        'Клики',
        'Корзины',
        'Заказы',
        'Выкупы',
      ])
    })

    it('labels each stage with its share of the one ABOVE it', () => {
      // Stage-over-stage, not share-of-top: it is the number that says which
      // step is leaking.
      const stages = chart('funnel', [], { totals: TOTALS }).option.series[0].data

      expect(stages.map((stage) => stage.conversion)).toEqual([null, 20, 25, 80])
    })

    it('keeps the journey order rather than sorting by size', () => {
      // Sorted by value, a stage that GREW would quietly change places and the
      // shape would stop being a funnel.
      expect(chart('funnel', [], { totals: TOTALS }).option.series[0].sort).toBe('none')
    })

    it('says «нет данных» rather than summing the days itself', () => {
      // The totals are the backend's; adding up matrix cells here is exactly
      // the arithmetic the no-frontend-math rule forbids.
      expect(chart('funnel').empty).toBe(true)
    })

    it('is joined by a conversion TREND, which a funnel cannot show', () => {
      const conversion = chart('conversion')
      const axes = [conversion.option.yAxis].flat()

      expect(axes.map((axis) => axis.name)).toEqual(['%'])
      expect(conversion.option.series.length).toBeGreaterThan(1)
    })
  })

  it('names and colours the legend for the panel to render in HTML', () => {
    // On the canvas the legend scrolled away with the days it labels.
    const sales = chart('sales')

    expect(sales.legend.map((e) => e.name)).toEqual(sales.option.series.map((e) => e.name))
    expect(sales.option.legend).toBeUndefined()
  })

  it('flags a slide whose every series is blank, and keeps its tab', () => {
    const sales = chart('sales', [row('order_sum', { total: [null, null] })])

    expect(sales.empty).toBe(true)
    expect(buildChartSpecs(matrixView([])).map((e) => e.key)).toContain('sales')
  })

  it('labels the x axis by day, shortened to fit a long window', () => {
    expect(chart('sales').option.xAxis.data).toEqual(['01.07', '02.07'])
  })

  it('follows the matrix stride when reading a bucket other than the first', () => {
    // A day section is COLUMNS_PER_DAY wide; reading with the wrong stride
    // silently returns another bucket's number, which still renders.
    const view = matrixView([row('orders', { organic: [7, 9] })])
    const ordersRow = view.rows.find((r) => r.key === 'orders')
    const organicColumn = TRAFFIC_COLUMNS.findIndex((c) => c.key === 'organic')

    expect(ordersRow.cells[COLUMNS_PER_DAY + organicColumn].raw).toBe(9)
    expect(
      buildChartSpecs(view)
        .find((e) => e.key === 'orders_mix')
        .option.series.find((s) => s.name === 'Органика').data,
    ).toEqual([7, 9])
  })
})
