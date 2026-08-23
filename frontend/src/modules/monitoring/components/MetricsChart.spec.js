import { mount } from '@vue/test-utils'

import MetricsChart from '@/modules/monitoring/components/MetricsChart.vue'
import { AGGREGATE_METRIC_GROUPS } from '@/modules/monitoring/metricChart'
import { TRAFFIC_COLUMNS, buildMetricsMatrix } from '@/modules/monitoring/metricsMatrix'

const DAYS = ['2026-07-01', '2026-07-02']

/** A backend matrix row: flat, day-major, one cell per bucket per day. */
function row(key, valuesByBucket) {
  const values = DAYS.flatMap((_, day) =>
    TRAFFIC_COLUMNS.map((column) => valuesByBucket[column.key]?.[day] ?? null),
  )
  return { key, values }
}

/** The display matrix the store hands the chart, built the way the store does. */
function matrixView(rows = []) {
  return buildMetricsMatrix({
    nm_id: 1,
    matrix: { days: DAYS, buckets: TRAFFIC_COLUMNS.map((column) => column.key), rows },
  })
}

/** Some data for every metric the default selection draws. */
const POPULATED = [
  row('spend', { total: [100, 200] }),
  row('drr_sales', { total: [3, 6] }),
  row('orders', { total: [4, 8] }),
  row('order_sum', { total: [1000, 2000] }),
]

/**
 * A stub that DECLARES the props, so a test can read the option that reached
 * it. `stubs: { BaseChart: true }` renders an element but drops the props into
 * attrs, where the option arrives stringified and useless.
 */
const BaseChartStub = {
  name: 'BaseChart',
  props: ['option', 'height'],
  template: '<div class="base-chart-stub" />',
}

/**
 * Mounted for real except the chart itself: the picker is a child component and
 * stubbing everything would leave nothing to click, while `BaseChart` is
 * replaced because jsdom has no canvas for ECharts to draw on.
 */
function mountChart(props = {}) {
  return mount(MetricsChart, {
    props: { view: matrixView(POPULATED), ...props },
    global: { stubs: { BaseChart: BaseChartStub } },
  })
}

const chips = (wrapper) => wrapper.findAll('button[aria-pressed]')
const chip = (wrapper, label) => chips(wrapper).find((button) => button.text() === label)
const legend = (wrapper) =>
  wrapper.findAll('[aria-label="Показано на графике"] li').map((item) => item.text())

describe('MetricsChart', () => {
  it('renders nothing at all when the window has no days', () => {
    // The block belongs to a loaded SKU; an empty window has no chart to show.
    const wrapper = mountChart({ view: { days: [], rows: [] } })

    expect(wrapper.find('section').exists()).toBe(false)
  })

  it('opens on its default metrics rather than on an empty plot', () => {
    // A chart that starts blank makes the reader do work before it says
    // anything; the default is the money question.
    const wrapper = mountChart()

    expect(legend(wrapper)).toEqual(expect.arrayContaining(['Затраты, ₽', 'ДРР от продаж, %']))
  })

  it('draws a metric once its chip is ticked', () => {
    const wrapper = mountChart()

    return chip(wrapper, 'Заказы, шт')
      .trigger('click')
      .then(() => {
        expect(legend(wrapper)).toContain('Заказы, шт')
      })
  })

  it('stops drawing a metric once its chip is unticked', async () => {
    const wrapper = mountChart()

    await chip(wrapper, 'Затраты, ₽').trigger('click')

    expect(legend(wrapper)).not.toContain('Затраты, ₽')
  })

  it('asks for a selection rather than drawing empty axes', async () => {
    // Unticking everything is a legitimate state, not an error.
    const wrapper = mountChart()

    await chip(wrapper, 'Затраты, ₽').trigger('click')
    await chip(wrapper, 'ДРР от продаж, %').trigger('click')

    expect(wrapper.text()).toContain('Выберите метрики')
    expect(wrapper.findComponent({ name: 'BaseChart' }).exists()).toBe(false)
  })

  it('says so when the period holds nothing for the metrics picked', async () => {
    // Different from an empty selection: the reader chose, and the window is
    // simply blank there.
    const wrapper = mountChart({ view: matrixView([row('spend', { total: [null, null] })]) })

    await chip(wrapper, 'ДРР от продаж, %').trigger('click')

    expect(wrapper.text()).toContain('нет данных')
  })

  it('replots against the index when the mode is switched', async () => {
    // Behaviour, not wiring: the same metric must reach the plot rebased.
    const wrapper = mountChart({ view: matrixView([row('spend', { total: [200, 400] })]) })
    const plotted = () => wrapper.findComponent({ name: 'BaseChart' }).props('option')

    await chip(wrapper, 'ДРР от продаж, %').trigger('click')
    expect(plotted().series[0].data).toEqual([200, 400])

    await wrapper
      .findAll('button')
      .find((button) => button.text() === 'Индекс')
      .trigger('click')

    expect(plotted().series[0].data).toEqual([100, 200])
  })

  it('pins the y axis beside the plot rather than inside the scroller', async () => {
    // The frozen column: the axis stands still while the days scroll past it,
    // the way the metrics table pins its metric names.
    const wrapper = mountChart()

    const charts = wrapper.findAllComponents({ name: 'BaseChart' })
    expect(charts).toHaveLength(2)
    // The scrolling copy hides the labels the pinned copy carries.
    const plot = charts[1].props('option')
    expect([plot.yAxis].flat().every((axis) => axis.axisLabel.show === false)).toBe(true)
  })

  it('offers the catalogue it was handed, not the per-SKU one', async () => {
    // The account-wide page has no prices and no CTR to offer.
    const wrapper = mountChart({
      groups: AGGREGATE_METRIC_GROUPS,
      defaultMetrics: ['order_sum'],
    })

    const labels = chips(wrapper).map((button) => button.text())
    expect(labels).toContain('Заказы, ₽')
    expect(labels).not.toContain('Цена покупателя, ₽')
    expect(labels).not.toContain('CTR, %')
  })

  it('groups the chips under «Реклама», «Воронка» and «Общие»', () => {
    // Visual separation only — but a reader looks for a metric by family, and
    // the groups are how they find it.
    const wrapper = mountChart()

    expect(wrapper.text()).toContain('Реклама')
    expect(wrapper.text()).toContain('Воронка')
    expect(wrapper.text()).toContain('Общие')
  })
})
