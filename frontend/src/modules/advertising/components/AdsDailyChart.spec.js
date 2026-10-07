import { mount } from '@vue/test-utils'

import AdsDailyChart from '@/modules/advertising/components/AdsDailyChart.vue'

/** Declares its props, so the option that reached the chart can be read. */
const BaseChartStub = {
  name: 'BaseChart',
  props: ['option', 'height'],
  template: '<div />',
}

const DAYS = [
  { day: '2026-09-01', spend: '100', bonus: '20', sales: '1000' },
  { day: '2026-09-02', spend: '120', bonus: '0', sales: '900' },
]

function mountChart() {
  return mount(AdsDailyChart, {
    props: { days: DAYS, currency: 'KGS', showBonus: true, showDrr: true },
    global: { stubs: { BaseChart: BaseChartStub } },
  })
}

const seriesNames = (wrapper) =>
  wrapper
    .findComponent(BaseChartStub)
    .props('option')
    .series.map((s) => s.name)
const legendButton = (wrapper, name) =>
  wrapper.findAll('button').find((button) => button.text() === name)

describe('AdsDailyChart — the legend switches lines', () => {
  it('hides a line on a click and brings it back on the next', async () => {
    const wrapper = mountChart()

    await legendButton(wrapper, 'Промо-бонусы').trigger('click')
    const hidden = seriesNames(wrapper)
    await legendButton(wrapper, 'Промо-бонусы').trigger('click')

    expect(hidden).toEqual(['Расход с баланса', 'ДРР от продаж'])
    expect(seriesNames(wrapper)).toEqual(['Расход с баланса', 'Промо-бонусы', 'ДРР от продаж'])
  })

  it('takes the percent axis away with the ДРР line', async () => {
    const wrapper = mountChart()

    await legendButton(wrapper, 'ДРР от продаж').trigger('click')

    expect(wrapper.findComponent(BaseChartStub).props('option').yAxis[1].show).toBe(false)
    expect(legendButton(wrapper, 'ДРР от продаж').attributes('aria-pressed')).toBe('false')
  })
})
