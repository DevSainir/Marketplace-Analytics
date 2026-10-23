import { mount } from '@vue/test-utils'

import SkuPicker from '@/modules/abTests/components/SkuPicker.vue'

const DRESS = {
  nm_id: 995716075,
  vendor_code: 'KID_DRESS',
  title: 'Dress',
  orders_7d: 12,
  has_ads: true,
}
const SUIT = {
  nm_id: 1948347102,
  vendor_code: 'KID_SUIT',
  title: 'Suit',
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
    // rest of the form until the user chose a SKU they may not have wanted.
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
  it('shows the picked SKU without swapping the input out', async () => {
    // The "change" button existed only because the input disappeared. It is
    // gone, so the input must survive the pick and carry the chosen SKU.
    const wrapper = picker()
    await wrapper.get('[data-testid="sku-search"]').trigger('focus')
    await wrapper.get('[data-testid="sku-option"]').trigger('click')
    await wrapper.setProps({ modelValue: DRESS })

    expect(wrapper.get('[data-testid="sku-search"]').element.value).toBe('KID_DRESS')
    expect(wrapper.get('[data-testid="picked-sku"]').text()).toContain('995716075')
  })

  it('drops the picked card as soon as the SKU is edited', async () => {
    // Otherwise the box could read "KID_SUIT" while the form still submitted
    // the card behind "KID_DRESS" — a test created against the wrong SKU.
    const wrapper = picker({ modelValue: DRESS })

    await wrapper.get('[data-testid="sku-search"]').setValue('KID_SU')

    expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([null])
    expect(wrapper.emitted('search').at(-1)).toEqual(['KID_SU'])
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
      expect.stringContaining('KID_DRESS'),
      expect.stringContaining('KID_SUIT'),
    ])
    expect(rows[0].text()).toContain('ads')
    expect(rows[0].text()).toContain('12 orders/wk')
    expect(rows[1].text()).not.toContain('ads')
  })
})
