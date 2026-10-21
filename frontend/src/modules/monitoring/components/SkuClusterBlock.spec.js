import { mount } from '@vue/test-utils'

import SkuClusterBlock from '@/modules/monitoring/components/SkuClusterBlock.vue'

const CLUSTERS = [
  {
    cluster: 'носки мужские',
    views: 1000,
    clicks: 50,
    ctr: 5,
    orders: 4,
    spend: 250,
    cpc: 5,
    avg_position: 6.2,
    days_count: 3,
  },
]

const mountBlock = (props = {}) =>
  mount(SkuClusterBlock, { props: { clusters: CLUSTERS, ...props } })

it('shows the SKU’s clusters without anyone typing a phrase', () => {
  // The stored half describes the SKU, not a search: it must render on its own,
  // which is why it is a section of its own since the live probe moved out.
  const wrapper = mountBlock()

  expect(wrapper.text()).toContain('носки мужские')
  // formatNumber uses ru-RU grouping, i.e. a non-breaking space.
  expect(wrapper.text().replace(/\u00a0/g, ' ')).toContain('1 000')
})

it('renders an unreported average ad position as a dash, not zero', () => {
  // Null means WB never reported a position; 0 would read as "first place".
  const wrapper = mountBlock({ clusters: [{ ...CLUSTERS[0], avg_position: null }] })

  expect(wrapper.find('tbody tr').text()).toContain('—')
})

it('carries its own heading, so an empty table cannot read as a broken probe', () => {
  // Regression: the two halves shared one «Поиск по кластерам» title, and an
  // empty advertising table looked like the position check had failed.
  const wrapper = mountBlock({ clusters: [], loaded: true })

  expect(wrapper.get('h2').text()).toBe('Рекламные кластеры')
  expect(wrapper.text()).toContain('реклама этого артикула не показывалась')
})
