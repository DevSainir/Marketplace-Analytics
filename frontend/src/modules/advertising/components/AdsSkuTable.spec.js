import { mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'

import AdsSkuTable from '@/modules/advertising/components/AdsSkuTable.vue'
import { groupRows, toRows, totalRow } from '@/modules/advertising/skuModel'

const SKUS = [
  {
    vendor_code: 'm-a',
    nm_id: 1,
    subject: 'Брюки',
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

function mountTable() {
  const rows = groupRows(toRows(SKUS), 'sku', 100)
  return mount(AdsSkuTable, {
    props: {
      rows,
      total: totalRow(rows, 100),
      labelHeader: 'Артикул',
      currency: 'KGS',
      showBonus: true,
    },
    global: { plugins: [[PrimeVue, { unstyled: true }]] },
  })
}

describe('AdsSkuTable — an article opens into its display zones', () => {
  it('shows the zones under the row only once the ▶ is clicked', async () => {
    const wrapper = mountTable()
    expect(wrapper.text()).not.toContain('Зона показа')

    await wrapper.find('button[aria-expanded]').trigger('click')

    const text = wrapper.text()
    expect(text).toContain('Единая ставка · Полки')
    expect(text).toContain('Ручной поиск · Поиск')
    expect(text.indexOf('Единая ставка · Полки')).toBeLessThan(text.indexOf('Ручной поиск'))
  })
})
