import { mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'

import AdsSkuTable from '@/modules/advertising/components/AdsSkuTable.vue'
import { groupRows, toRows, totalRow } from '@/modules/advertising/skuModel'

const SKUS = [
  {
    vendor_code: 'm-a',
    nm_id: 1,
    subject: 'Trousers',
    brand: 'X',
    spend: '100',
    bonus: '10',
    spend_settled: '100',
    bonus_settled: '10',
    sales: '1000',
    orders: 3,
    zones: [
      { zone: 'cpm_unified_shelves', spend: '75', bonus: '10' },
      { zone: 'cpm_manual_search', spend: '25', bonus: '0' },
    ],
  },
]

function mountTable(grain = 'sku', groups = []) {
  const rows = groupRows(toRows(SKUS), grain, 100, groups)
  return mount(AdsSkuTable, {
    props: {
      rows,
      total: totalRow(toRows(SKUS), 100),
      labelHeader: 'SKU',
      currency: 'KGS',
      showBonus: true,
    },
    global: { plugins: [[PrimeVue, { unstyled: true }]] },
  })
}

describe('AdsSkuTable — an article opens into its display zones', () => {
  it('shows the zones under the row only once the ▶ is clicked', async () => {
    const wrapper = mountTable()
    expect(wrapper.text()).not.toContain('Placement')

    await wrapper.find('button[aria-expanded]').trigger('click')

    const text = wrapper.text()
    expect(text).toContain('Unified bid · Shelves')
    expect(text).toContain('Manual search · Search')
    expect(text.indexOf('Unified bid · Shelves')).toBeLessThan(text.indexOf('Manual search'))
  })
})

describe('AdsSkuTable — names', () => {
  it('prints an article code uppercase and a group or the total as named', () => {
    const bySku = mountTable().text()
    const byGroup = mountTable('group', [{ id: 'a', name: 'Summer', nm_ids: [1] }]).text()

    expect(bySku).toContain('M-A')
    expect(byGroup).toContain('Summer')
    expect(byGroup).not.toContain('SUMMER')
    expect(byGroup).toContain('Total · 1')
  })
})
