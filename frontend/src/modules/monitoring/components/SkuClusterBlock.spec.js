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

const POSITION = {
  nm_id: 953770957,
  query: 'носки',
  normalized_query: 'мужские носки',
  checked_at: '2026-08-14T09:00:00Z',
  total_found: 111119,
  positions_scanned: 300,
  truncated: true,
  position: 7,
  page: 1,
  position_on_page: 7,
  other_skus: [{ nm_id: 144178006, vendor_code: 'M-TRX01-BEJ', position: 41 }],
}

const mountBlock = (props = {}) =>
  mount(SkuClusterBlock, { props: { clusters: CLUSTERS, ...props } })

it('shows the SKU’s clusters without anyone typing a phrase', () => {
  // The stored half is the block's default content: it describes the SKU, not a
  // search, so it must not wait on the search bar.
  const wrapper = mountBlock()

  expect(wrapper.text()).toContain('носки мужские')
  // formatNumber uses ru-RU grouping, i.e. a non-breaking space.
  expect(wrapper.text().replace(/\u00a0/g, ' ')).toContain('1 000')
})

it('renders an unreported average ad position as a dash, not zero', () => {
  // Null means WB never reported a position; 0 would read as «первое место».
  const wrapper = mountBlock({ clusters: [{ ...CLUSTERS[0], avg_position: null }] })

  expect(wrapper.find('tbody tr').text()).toContain('—')
})

it('reports the live rank with its page and WB’s own phrasing', () => {
  const wrapper = mountBlock({ position: POSITION })

  expect(wrapper.text()).toContain('7')
  expect(wrapper.text()).toContain('мужские носки')
  expect(wrapper.text()).toContain('M-TRX01-BEJ')
})

it('names the scanned depth when the SKU did not rank inside it', () => {
  // A SKU can rank deeper than the probe looks, so the empty state states the
  // depth instead of implying the SKU is absent from WB.
  const wrapper = mountBlock({ position: { ...POSITION, position: null, page: null } })

  expect(wrapper.text()).toContain('не найден в первых 300')
})

it('says WB did not answer instead of reporting the SKU as unranked', () => {
  // The block's central rule: «не проверилось» and «нет в выдаче» lead a seller
  // to opposite decisions about the bid.
  const wrapper = mountBlock({ positionError: 'WB притормозил запрос. Повторите через минуту.' })

  expect(wrapper.text()).toContain('притормозил')
  expect(wrapper.text()).not.toContain('не найден в первых')
})

it('emits the typed phrase on submit and never an empty one', async () => {
  const wrapper = mountBlock()

  await wrapper.get('form').trigger('submit')
  await wrapper.get('input').setValue('носки')
  await wrapper.get('form').trigger('submit')

  expect(wrapper.emitted('check')).toEqual([['носки']])
})
