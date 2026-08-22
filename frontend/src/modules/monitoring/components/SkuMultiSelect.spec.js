import { mount } from '@vue/test-utils'

import SkuMultiSelect from '@/modules/monitoring/components/SkuMultiSelect.vue'

const ITEMS = [
  { nm_id: 1, vendor_code: 'm-tshirt-01', title: 'Футболка хлопковая' },
  { nm_id: 2, vendor_code: 'm-mug-02', title: 'Кружка керамическая' },
]

function mountPicker(props = {}) {
  return mount(SkuMultiSelect, { props: { items: ITEMS, modelValue: [], ...props } })
}

const openMenu = (wrapper) => wrapper.find('button[aria-haspopup="listbox"]').trigger('click')
const options = (wrapper) => wrapper.findAll('[role="option"]')

describe('SkuMultiSelect', () => {
  it('says «все» while nothing is chosen — the empty selection IS every SKU', () => {
    // A charts page that showed nothing until you picked something would be a
    // worse default than the whole account, so empty means all, and the
    // trigger has to say so or the page misstates its own scope.
    expect(mountPicker().text()).toContain('Все артикулы (2)')
  })

  it('names the single choice, and counts the rest', () => {
    expect(mountPicker({ modelValue: [2] }).text()).toContain('M-MUG-02')
    expect(mountPicker({ modelValue: [1, 2] }).text()).toContain('Выбрано артикулов: 2')
  })

  it('adds and removes a SKU without mutating the prop', async () => {
    const wrapper = mountPicker({ modelValue: [1] })
    await openMenu(wrapper)

    await options(wrapper)[1].trigger('click')
    expect(wrapper.emitted('update:modelValue').at(-1)[0]).toEqual([1, 2])

    await options(wrapper)[0].trigger('click')
    expect(wrapper.emitted('update:modelValue').at(-1)[0]).toEqual([])
  })

  it('searches by article, nm ID and title alike', async () => {
    const wrapper = mountPicker()
    await openMenu(wrapper)

    await wrapper.find('input[type="text"]').setValue('кружка')
    expect(options(wrapper)).toHaveLength(1)

    await wrapper.find('input[type="text"]').setValue('1')
    expect(options(wrapper)).toHaveLength(1)

    await wrapper.find('input[type="text"]').setValue('нет такого')
    expect(wrapper.text()).toContain('Ничего не найдено')
  })

  it('«Выбрать все» clears the selection rather than listing every id', async () => {
    // Same end state, but an empty list keeps meaning «whatever the workspace
    // holds» — a selection frozen at today's ids would quietly exclude a SKU
    // added tomorrow.
    const wrapper = mountPicker({ modelValue: [1] })
    await openMenu(wrapper)

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Выбрать все')
      .trigger('click')

    expect(wrapper.emitted('update:modelValue').at(-1)[0]).toEqual([])
  })
})
