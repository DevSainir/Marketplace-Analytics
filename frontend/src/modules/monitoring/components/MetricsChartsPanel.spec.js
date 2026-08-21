import { shallowMount } from '@vue/test-utils'

import MetricsChartsPanel from '@/modules/monitoring/components/MetricsChartsPanel.vue'
import { TRAFFIC_COLUMNS, buildMetricsMatrix } from '@/modules/monitoring/metricsMatrix'

const DAYS = ['2026-07-01', '2026-07-02']

/** The display matrix the store hands the panel, built the way the store does. */
function view(rows = []) {
  return buildMetricsMatrix({
    nm_id: 1,
    matrix: { days: DAYS, buckets: TRAFFIC_COLUMNS.map((column) => column.key), rows },
  })
}

/** `shallow` stubs the async ECharts child — jsdom has no canvas to draw on. */
function mountPanel(props = { view: view() }) {
  return shallowMount(MetricsChartsPanel, { props })
}

const tabs = (wrapper) => wrapper.findAll('[role="tab"]')
const selected = (wrapper) =>
  tabs(wrapper).findIndex((tab) => tab.attributes('aria-selected') === 'true')

describe('MetricsChartsPanel', () => {
  it('renders nothing at all when the window has no days', () => {
    const wrapper = mountPanel({ view: { days: [], rows: [] } })

    expect(wrapper.find('section').exists()).toBe(false)
  })

  it('opens on the first chart and switches when a tab is clicked', async () => {
    const wrapper = mountPanel()

    expect(selected(wrapper)).toBe(0)
    await tabs(wrapper)[3].trigger('click')

    expect(selected(wrapper)).toBe(3)
  })

  it('steps the carousel with the arrow keys', async () => {
    const wrapper = mountPanel()
    const card = wrapper.find('[role="group"]')

    await card.trigger('keydown', { key: 'ArrowRight' })
    expect(selected(wrapper)).toBe(1)

    await card.trigger('keydown', { key: 'ArrowLeft' })
    expect(selected(wrapper)).toBe(0)
  })

  it('wraps at both ends rather than stopping', async () => {
    const wrapper = mountPanel()
    const card = wrapper.find('[role="group"]')
    const last = tabs(wrapper).length - 1

    // ← from the first slide lands on the last, and → from there comes back.
    await card.trigger('keydown', { key: 'ArrowLeft' })
    expect(selected(wrapper)).toBe(last)

    await card.trigger('keydown', { key: 'ArrowRight' })
    expect(selected(wrapper)).toBe(0)
  })

  it('leaves other keys to the rest of the page', async () => {
    // The block sits under an editable table; swallowing every keystroke that
    // reaches it would break typing and the undo shortcuts.
    const wrapper = mountPanel()

    await wrapper.find('[role="group"]').trigger('keydown', { key: 'ArrowUp' })

    expect(selected(wrapper)).toBe(0)
  })

  it('says so instead of drawing an axis around nothing', () => {
    const wrapper = mountPanel()

    expect(wrapper.text()).toContain('нет данных')
    expect(wrapper.findComponent({ name: 'BaseChart' }).exists()).toBe(false)
  })

  it('draws the chart once the slide has values', async () => {
    const values = DAYS.flatMap(() =>
      TRAFFIC_COLUMNS.map((column) => (column.key === 'total' ? 1000 : null)),
    )
    const wrapper = mountPanel({ view: view([{ key: 'order_sum', values }]) })

    expect(wrapper.findComponent({ name: 'BaseChart' }).exists()).toBe(true)
    expect(wrapper.text()).not.toContain('нет данных')
  })
})
