import { mount } from '@vue/test-utils'

import SkuSearchSelect from '@/modules/monitoring/components/SkuSearchSelect.vue'

const ITEMS = [
  { nm_id: 111, vendor_code: 'M-TRX01-BLK', title: 'Брюки чёрные', is_out_of_stock: false },
  { nm_id: 222, vendor_code: 'M-TRX01-BEJ', title: 'Брюки бежевые', is_out_of_stock: true },
  { nm_id: 333, vendor_code: 'M-LNX01-BLU', title: 'Рубашка синяя', is_out_of_stock: false },
]

function optionLabels(wrapper) {
  return wrapper.findAll('[role="option"]').map((option) => option.text())
}

describe('SkuSearchSelect', () => {
  it('opens the dropdown on focus with every SKU listed', async () => {
    const wrapper = mount(SkuSearchSelect, { props: { items: ITEMS } })
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false)

    await wrapper.find('input').trigger('focus')

    expect(wrapper.findAll('[role="option"]')).toHaveLength(3)
  })

  it('filters the list as the user types, matching code, title and nm ID', async () => {
    const wrapper = mount(SkuSearchSelect, { props: { items: ITEMS } })
    const input = wrapper.find('input')

    await input.setValue('m-trx')
    expect(optionLabels(wrapper)).toHaveLength(2)

    await input.setValue('рубашка')
    expect(optionLabels(wrapper)).toEqual([expect.stringContaining('M-LNX01-BLU')])

    await input.setValue('222')
    expect(optionLabels(wrapper)).toEqual([expect.stringContaining('M-TRX01-BEJ')])

    await input.setValue('нет такого')
    expect(wrapper.findAll('[role="option"]')).toHaveLength(0)
    expect(wrapper.find('[role="listbox"]').text()).toContain('Ничего не совпало')
  })

  it('emits select with the picked item and closes the dropdown', async () => {
    const wrapper = mount(SkuSearchSelect, { props: { items: ITEMS } })
    await wrapper.find('input').trigger('focus')

    await wrapper.findAll('[role="option"]')[2].trigger('click')

    expect(wrapper.emitted('select')).toEqual([[ITEMS[2]]])
    expect(wrapper.find('input').element.value).toBe('M-LNX01-BLU')
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
  })

  it('emits apply with the trimmed query on submit', async () => {
    const wrapper = mount(SkuSearchSelect, { props: { items: ITEMS } })

    await wrapper.find('input').setValue('  953770957  ')
    await wrapper.find('form').trigger('submit')

    expect(wrapper.emitted('apply')).toEqual([['953770957']])
  })

  it('highlights the currently analyzed SKU', async () => {
    const wrapper = mount(SkuSearchSelect, { props: { items: ITEMS, selectedId: 222 } })
    await wrapper.find('input').trigger('focus')

    const selected = wrapper.findAll('[role="option"]').filter(
      (option) => option.attributes('aria-selected') === 'true',
    )
    expect(selected).toHaveLength(1)
    expect(selected[0].text()).toContain('M-TRX01-BEJ')
  })

  it('shows the loading message instead of options while the list loads', async () => {
    const wrapper = mount(SkuSearchSelect, { props: { items: [], loading: true } })
    await wrapper.find('input').trigger('focus')

    expect(wrapper.find('[role="listbox"]').text()).toContain('Загружаем список SKU')
    expect(wrapper.findAll('[role="option"]')).toHaveLength(0)
  })
})
