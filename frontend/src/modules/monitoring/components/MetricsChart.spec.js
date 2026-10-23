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
/** In one workspace's units: priced in RUB, advertised in KGS. */
function matrixView(rows = [], currencies = { prices: 'RUB', ads: ['KGS'] }) {
  return buildMetricsMatrix(
    {
      nm_id: 1,
      matrix: { days: DAYS, buckets: TRAFFIC_COLUMNS.map((column) => column.key), rows },
    },
    currencies,
  )
}

/** Some data for every metric the default selection draws. */
const POPULATED = [
  row('spend', { total: [100, 200] }),
  row('views', { total: [5000, 7000] }),
  row('ctr', { total: [3, 6] }),
  row('carts', { total: [40, 60] }),
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
  wrapper.findAll('[aria-label="On the chart"] li').map((item) => item.text())

describe('MetricsChart', () => {
  it('renders nothing at all when the window has no days', () => {
    // The block belongs to a loaded SKU; an empty window has no chart to show.
    const wrapper = mountChart({ view: { days: [], rows: [] } })

    expect(wrapper.find('section').exists()).toBe(false)
  })

  it('carries its own title', () => {
    // It sits under two other blocks that name themselves; unnamed, it read as
    // an appendix to whichever table happened to be above it.
    expect(mountChart().find('h2').text()).toBe('Chart')
  })

  it('opens on its default metrics rather than on an empty plot', () => {
    // A chart that starts blank makes the reader do work before it says
    // anything: where the money goes (spend, views, CTR) and what came back (carts,
    // orders).
    const wrapper = mountChart()

    expect(legend(wrapper)).toEqual([
      'Spend',
      'Impressions',
      'CTR, %',
      'Add to cart, units',
      'Orders, units',
    ])
  })

  it('lists the legend in catalogue order, not in the order chips were clicked', () => {
    // The order is the plot's order too — the columns of a day are drawn in it
    // — so a stable legend and a stable chart are the same fact.
    const wrapper = mountChart({ defaultMetrics: [] })

    return chip(wrapper, 'Orders, units')
      .trigger('click')
      .then(() => chip(wrapper, 'Spend').trigger('click'))
      .then(() => {
        expect(legend(wrapper)).toEqual(['Spend', 'Orders, units'])
      })
  })

  it('offers no mode switch: everything is an index', async () => {
    // "Values" put "Orders" at 500,000 beside "Spend" at 7,000 on one
    // axis, which is a flat line and a lie about the smaller of the two.
    const wrapper = mountChart()

    const labels = wrapper.findAll('button').map((button) => button.text())
    expect(labels).not.toContain('Values')
    expect(labels).not.toContain('Index')
  })

  it('stops drawing a metric once its chip is unticked', async () => {
    const wrapper = mountChart()

    await chip(wrapper, 'Spend').trigger('click')

    expect(legend(wrapper)).not.toContain('Spend')
  })

  it('draws a metric once its chip is ticked', async () => {
    const wrapper = mountChart()

    await chip(wrapper, 'Clicks').trigger('click')

    expect(legend(wrapper)).toContain('Clicks')
  })

  it('asks for a selection rather than drawing empty axes', async () => {
    // Unticking everything is a legitimate state, not an error.
    const wrapper = mountChart({ defaultMetrics: [] })

    expect(wrapper.text()).toContain('Pick the metrics')
    expect(wrapper.findComponent({ name: 'BaseChart' }).exists()).toBe(false)
  })

  it('says so when the period holds nothing for the metrics picked', () => {
    // Different from an empty selection: the reader chose, and the window is
    // simply blank there.
    const wrapper = mountChart({
      view: matrixView([row('spend', { total: [null, null] })]),
      defaultMetrics: ['spend'],
    })

    expect(wrapper.text()).toContain('No data')
  })

  it('plots a single-unit pick as the values themselves', () => {
    // Behaviour, not wiring: one unit in the pick means one axis is already
    // true for it, so the numbers reach the plot unrebased.
    const wrapper = mountChart({
      view: matrixView([row('spend', { total: [200, 400] })]),
      defaultMetrics: ['spend'],
    })

    const plotted = wrapper.findComponent({ name: 'BaseChart' }).props('option')
    expect(plotted.series[0].data).toEqual([200, 400])
  })

  it('plots what has no ruler as an index', () => {
    // Unit counts and roubles each have a fixed scale; a percent has neither, so it is
    // drawn as a shape and the hover keeps the quantity.
    const wrapper = mountChart({
      view: matrixView([row('ctr', { total: [2, 4] })]),
      defaultMetrics: ['ctr'],
    })

    const plotted = wrapper.findComponent({ name: 'BaseChart' }).props('option')
    expect(plotted.series[0].data).toEqual([100, 200])
  })

  it('draws one plot with its axis inside it, not two side by side', async () => {
    // There is no ribbon any more, so there is nothing for a pinned axis copy
    // to stand beside: the whole window is on the card's own width.
    const wrapper = mountChart()

    const charts = wrapper.findAllComponents({ name: 'BaseChart' })
    expect(charts).toHaveLength(1)
    // And the two unit scales show their own numbers: the muted copy existed
    // only to stop them scrolling away from the pinned one.
    const axes = [charts[0].props('option').yAxis].flat()
    expect(axes.slice(0, 2).every((axis) => axis.axisLabel.show !== false)).toBe(true)
  })

  it('offers the catalogue it was handed, not the per-SKU one', async () => {
    // The account-wide page has no prices and no CTR to offer.
    const wrapper = mountChart({
      groups: AGGREGATE_METRIC_GROUPS,
      defaultMetrics: ['order_sum'],
    })

    const labels = chips(wrapper).map((button) => button.text())
    expect(labels).toContain('Orders')
    expect(labels).not.toContain('Customer price')
    expect(labels).not.toContain('CTR, %')
  })

  it('names a money chip without a unit while the currency is unknown', () => {
    // No unit beats a guessed one — and the chip must match the legend's name.
    const wrapper = mountChart({ view: matrixView(POPULATED, {}) })

    expect(chip(wrapper, 'Spend')).toBeDefined()
    expect(legend(wrapper)).toContain('Spend')
  })

  it('groups the chips under "Advertising", "Funnel" and "General"', () => {
    // Visual separation only — but a reader looks for a metric by family, and
    // the groups are how they find it.
    const wrapper = mountChart()

    expect(wrapper.text()).toContain('Advertising')
    expect(wrapper.text()).toContain('Funnel')
    expect(wrapper.text()).toContain('General')
  })
})
