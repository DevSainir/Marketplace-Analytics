import { buildAggregateChartSpecs } from '@/modules/monitoring/aggregateChartSpecs'
import { buildMetricsMatrix } from '@/modules/monitoring/metricsMatrix'

const DAYS = ['2026-08-10', '2026-08-11']
/** The aggregate endpoint serves «Общая» and «Органика» only. */
const BUCKETS = ['total', 'organic']

/** A matrix in the shape `/monitoring/charts` returns. */
function aggregateView(rows = []) {
  return buildMetricsMatrix({ nm_id: 0, matrix: { days: DAYS, buckets: BUCKETS, rows } })
}

/** Day-major values for a two-bucket matrix. */
function row(key, { total = [], organic = [] }) {
  return {
    key,
    values: DAYS.flatMap((_, day) => [total[day] ?? null, organic[day] ?? null]),
  }
}

const tabs = (charts) => charts.map((chart) => chart.tab)

describe('buildAggregateChartSpecs', () => {
  it('has no slides without a window', () => {
    expect(buildAggregateChartSpecs({ days: [], rows: [] })).toEqual([])
    expect(buildAggregateChartSpecs(null)).toEqual([])
  })

  it('reads the summed «Общая» series the endpoint serves', () => {
    const charts = buildAggregateChartSpecs(
      aggregateView([row('order_sum', { total: [1000, 2500] })]),
    )
    const sales = charts.find((chart) => chart.key === 'sales')

    expect(sales.option.series.find((s) => s.name === 'Заказы, ₽').data).toEqual([1000, 2500])
    expect(sales.empty).toBe(false)
  })

  it('leaves out every metric that cannot be summed across SKUs', () => {
    // Prices are per-card facts (the average of a T-shirt and a mug is a number
    // about nothing); «Выкупы» rides on a lagged cohort ratio the aggregate
    // endpoint does not compute; the traffic-type split is a per-card judgement
    // about a campaign-day. All three are absent rather than approximated.
    const labels = tabs(buildAggregateChartSpecs(aggregateView()))

    expect(labels).not.toContain('Цены')
    expect(labels).not.toContain('Расходы')
    expect(labels.join(' ')).not.toContain('Выкуп')
  })

  it('draws the funnel as a funnel, with the trend beside it', () => {
    expect(tabs(buildAggregateChartSpecs(aggregateView()))).toEqual(
      expect.arrayContaining(['Воронка', 'Конверсии', 'Этапы по дням']),
    )
  })

  it('offers a «Общий» picker over the metrics the endpoint actually serves', () => {
    const charts = buildAggregateChartSpecs(aggregateView(), { overview: ['orders', 'spend'] })
    const overview = charts.find((chart) => chart.key === 'overview')

    expect(overview.pickable).toBe(true)
    expect(overview.option.series.map((s) => s.name)).toEqual(['Заказы, шт', 'Затраты, ₽'])
  })

  it('draws «Органика» against the total rather than subtracting anything itself', () => {
    // The organic half is the backend's own «всего минус реклама»: the gap
    // between the two lines IS the advertising, computed server-side.
    const charts = buildAggregateChartSpecs(
      aggregateView([row('orders', { total: [40, 50], organic: [28, 30] })]),
    )
    const mix = charts.find((chart) => chart.key === 'orders_mix')
    const byName = new Map(mix.option.series.map((entry) => [entry.name, entry.data]))

    expect(byName.get('Заказы, шт')).toEqual([40, 50])
    expect(byName.get('Заказы органика, шт')).toEqual([28, 30])
  })

  it('gives one axis per unit, never two to one unit', () => {
    // The same rule as the per-SKU page: metrics that can be compared share a
    // ruler; metrics in different units get one each, labelled «₽» or «%».
    for (const chart of buildAggregateChartSpecs(aggregateView())) {
      if (chart.funnel) continue // a funnel has no value axis at all
      const axes = [chart.option.yAxis].flat()
      const named = axes.map((axis) => axis.name).filter(Boolean)

      expect(new Set(named).size).toBe(named.length)
    }
  })
})
