import { mount } from '@vue/test-utils'

import SkuPicker from '@/modules/abTests/components/SkuPicker.vue'

const DRESS = {
  nm_id: 995716075,
  vendor_code: 'ДЕТ_ПЛАТЬЕ',
  title: 'Платье',
  orders_7d: 12,
  has_ads: true,
}
const SUIT = {
  nm_id: 1948347102,
  vendor_code: 'ДЕТ_КОСТЮМ',
  title: 'Костюм',
  orders_7d: 3,
  has_ads: false,
}

function picker(props = {}) {
  return mount(SkuPicker, {
    props: { options: [DRESS, SUIT], modelValue: null, ...props },
    attachTo: document.body,
  })
}

const list = (wrapper) => wrapper.find('[data-testid="sku-options"]')

describe('the option list can be dismissed', () => {
  it('closes on Escape', async () => {
    // It could previously only be dismissed by picking something: neither
    // Escape nor a click elsewhere reached it, so an open list covered the
    // rest of the form until the user chose an article they may not have wanted.
    const wrapper = picker()
    await wrapper.get('[data-testid="sku-search"]').trigger('focus')
    expect(list(wrapper).exists()).toBe(true)

    await wrapper.get('[data-testid="sku-search"]').trigger('keydown.esc')

    expect(list(wrapper).exists()).toBe(false)
  })

  it('closes when focus leaves the whole combobox', async () => {
    // What a click anywhere else on the page does. `relatedTarget` inside the
    // combobox is how an option click keeps the list open long enough to fire.
    const wrapper = picker()
    await wrapper.get('[data-testid="sku-search"]').trigger('focus')

    await wrapper.get('[data-testid="sku-search"]').trigger('focusout', { relatedTarget: null })

    expect(list(wrapper).exists()).toBe(false)
  })

  it('keeps the list open while focus moves between its own options', async () => {
    const wrapper = picker()
    await wrapper.get('[data-testid="sku-search"]').trigger('focus')
    const option = wrapper.findAll('[data-testid="sku-option"]')[0].element

    await wrapper.get('[data-testid="sku-search"]').trigger('focusout', { relatedTarget: option })

    expect(list(wrapper).exists()).toBe(true)
  })
})

describe('the field stays a search field after a card is picked', () => {
  it('shows the picked article without swapping the input out', async () => {
    // The «сменить» button existed only because the input disappeared. It is
    // gone, so the input must survive the pick and carry the chosen article.
    const wrapper = picker()
    await wrapper.get('[data-testid="sku-search"]').trigger('focus')
    await wrapper.get('[data-testid="sku-option"]').trigger('click')
    await wrapper.setProps({ modelValue: DRESS })

    expect(wrapper.get('[data-testid="sku-search"]').element.value).toBe('ДЕТ_ПЛАТЬЕ')
    expect(wrapper.get('[data-testid="picked-sku"]').text()).toContain('995716075')
  })

  it('drops the picked card as soon as the article is edited', async () => {
    // Otherwise the box could read «ДЕТ_КОСТЮМ» while the form still submitted
    // the card behind «ДЕТ_ПЛАТЬЕ» — a test created against the wrong article.
    const wrapper = picker({ modelValue: DRESS })

    await wrapper.get('[data-testid="sku-search"]').setValue('ДЕТ_КОС')

    expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([null])
    expect(wrapper.emitted('search').at(-1)).toEqual(['ДЕТ_КОС'])
  })
})

describe('the list explains the order it arrived in', () => {
  it('renders the options in the order given, with their ranking marks', async () => {
    // The backend ranks advertised cards first, then last week's orders. A
    // client-side re-sort would silently undo that; a list with no visible
    // reason for its order reads as arbitrary.
    const wrapper = picker()
    await wrapper.get('[data-testid="sku-search"]').trigger('focus')

    const rows = wrapper.findAll('[data-testid="sku-option"]')

    expect(rows.map((row) => row.text())).toEqual([
      expect.stringContaining('ДЕТ_ПЛАТЬЕ'),
      expect.stringContaining('ДЕТ_КОСТЮМ'),
    ])
    expect(rows[0].text()).toContain('реклама')
    expect(rows[0].text()).toContain('12 зак/нед')
    expect(rows[1].text()).not.toContain('реклама')
  })
})
