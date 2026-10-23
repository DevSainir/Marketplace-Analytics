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
const legendBox = (wrapper, name) =>
  wrapper
    .findAll('label')
    .find((label) => label.text() === name)
    .find('input[type="checkbox"]')

describe('AdsDailyChart — the legend checkboxes switch lines', () => {
  it('hides a line when its box is unticked and brings it back when ticked', async () => {
    const wrapper = mountChart()

    await legendBox(wrapper, 'Promo bonuses').setValue(false)
    const hidden = seriesNames(wrapper)
    await legendBox(wrapper, 'Promo bonuses').setValue(true)

    expect(hidden).toEqual(['Spend from balance', 'ACoS (sales)'])
    expect(seriesNames(wrapper)).toEqual(['Spend from balance', 'Promo bonuses', 'ACoS (sales)'])
  })

  it('takes the percent axis away with the ACoS line', async () => {
    const wrapper = mountChart()

    await legendBox(wrapper, 'ACoS (sales)').setValue(false)

    expect(wrapper.findComponent(BaseChartStub).props('option').yAxis[1].show).toBe(false)
    expect(legendBox(wrapper, 'ACoS (sales)').element.checked).toBe(false)
  })
})
