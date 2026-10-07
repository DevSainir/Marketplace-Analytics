import { mount } from '@vue/test-utils'

import BusyRegion from '@/core/components/BusyRegion.vue'

/** A block with figures in it, as a page passes them in. */
function mountRegion(busy) {
  return mount(BusyRegion, { props: { busy }, slots: { default: '<p>1 234 ₽</p>' } })
}

describe('BusyRegion', () => {
  it('keeps the figures on screen while new ones load', () => {
    // Blanking the block on every reload — a period change, a ticked flag —
    // made whole tables vanish and the page jump. The figures stay instead.
    const wrapper = mountRegion(true)

    expect(wrapper.text()).toContain('1 234 ₽')
  })

  it('takes clicks away from the stale figures while they are being replaced', () => {
    // A click on a stale row would act on numbers about to change under it.
    const wrapper = mountRegion(true)

    expect(wrapper.find('.pointer-events-none').exists()).toBe(true)
    expect(wrapper.attributes('aria-busy')).toBe('true')
  })

  it('gives the block back once the new figures land', () => {
    const wrapper = mountRegion(false)

    expect(wrapper.find('.pointer-events-none').exists()).toBe(false)
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })
})
