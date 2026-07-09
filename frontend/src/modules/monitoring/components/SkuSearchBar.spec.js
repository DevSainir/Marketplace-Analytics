import { mount } from '@vue/test-utils'

import { isoDaysAgo } from '@/core/utils/dates'
import SkuSearchBar from '@/modules/monitoring/components/SkuSearchBar.vue'

describe('SkuSearchBar', () => {
  it('defaults the window to the local last 7 days', () => {
    const wrapper = mount(SkuSearchBar)
    const [from, to] = wrapper.findAll('input[type="date"]')

    expect(from.element.value).toBe(isoDaysAgo(6))
    expect(to.element.value).toBe(isoDaysAgo(0))
  })

  it('seeds fields from initial props (URL deep link)', () => {
    const wrapper = mount(SkuSearchBar, {
      props: {
        initialQuery: 'M-TRX01-BLK',
        initialDateFrom: '2026-07-01',
        initialDateTo: '2026-07-07',
      },
    })

    expect(wrapper.find('input[type="text"]').element.value).toBe('M-TRX01-BLK')
    const [from, to] = wrapper.findAll('input[type="date"]')
    expect(from.element.value).toBe('2026-07-01')
    expect(to.element.value).toBe('2026-07-07')
  })

  it('emits a search payload matching the API params', async () => {
    const wrapper = mount(SkuSearchBar, {
      props: { initialDateFrom: '2026-07-01', initialDateTo: '2026-07-07' },
    })

    await wrapper.find('input[type="text"]').setValue('  953770957  ')
    await wrapper.find('form').trigger('submit')

    expect(wrapper.emitted('search')).toEqual([
      [{ sku: '953770957', date_from: '2026-07-01', date_to: '2026-07-07' }],
    ])
  })

  it('does not emit for a blank query', async () => {
    const wrapper = mount(SkuSearchBar)

    await wrapper.find('form').trigger('submit')

    expect(wrapper.emitted('search')).toBeUndefined()
  })
})
