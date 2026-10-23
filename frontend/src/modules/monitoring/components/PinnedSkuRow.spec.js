import { mount } from '@vue/test-utils'

import PinnedSkuRow from '@/modules/monitoring/components/PinnedSkuRow.vue'
import { PIN_COLORS } from '@/modules/monitoring/pinColors'

// jsdom has no ResizeObserver, and the row observes its scroller on mount.
globalThis.ResizeObserver ??= class {
  observe() {}
  disconnect() {}
}

const ITEMS = [
  { nm_id: 1, vendor_code: 'AAA', title: 'A', color: null },
  { nm_id: 2, vendor_code: 'BBB', title: 'B', color: '#ff0000' },
]

function mountRow(props = {}) {
  return mount(PinnedSkuRow, { props: { items: ITEMS, ...props } })
}

const chips = (wrapper) => wrapper.findAll('.pin-chip')
const pencil = (wrapper) => wrapper.get('[aria-label="Edit pinned SKU colors"]')
/** The swatch buttons of the palette popover — absent until a chip is picked. */
const swatches = (wrapper) => wrapper.findAll(`[aria-label="${PIN_COLORS[0].label}"]`)

describe('paint mode', () => {
  it('analyzes a chip while the mode is closed', async () => {
    const wrapper = mountRow()

    await chips(wrapper)[0].trigger('click')

    expect(wrapper.emitted('select')).toEqual([[ITEMS[0]]])
  })

  it('explains itself until a chip is picked', async () => {
    const wrapper = mountRow()

    await pencil(wrapper).trigger('click')

    expect(wrapper.text()).toContain('Paint mode')
    expect(swatches(wrapper)).toHaveLength(0)
  })

  // The regression: the palette is what makes the mode usable, and it only
  // appears once a chip is the target. Without it the pencil opens a hint that
  // never turns into anything, so no colour can ever be picked.
  it('opens the palette on the picked chip instead of analyzing it', async () => {
    const wrapper = mountRow()

    await pencil(wrapper).trigger('click')
    await chips(wrapper)[1].trigger('click')

    expect(swatches(wrapper)).toHaveLength(1)
    expect(wrapper.text()).toContain('Color for "BBB"')
    expect(wrapper.emitted('select')).toBeUndefined()
  })

  it('recolors the picked chip when a swatch is clicked', async () => {
    const wrapper = mountRow()

    await pencil(wrapper).trigger('click')
    await chips(wrapper)[0].trigger('click')
    await swatches(wrapper)[0].trigger('click')

    expect(wrapper.emitted('recolor')).toEqual([[1, PIN_COLORS[0].value]])
  })

  it('clears the tint through "Remove color"', async () => {
    const wrapper = mountRow()

    await pencil(wrapper).trigger('click')
    await chips(wrapper)[1].trigger('click')
    await wrapper.get('[aria-pressed="false"].w-full').trigger('click')

    expect(wrapper.emitted('recolor')).toEqual([[2, null]])
  })

  it('stays open so a second chip can be painted next', async () => {
    const wrapper = mountRow()

    await pencil(wrapper).trigger('click')
    await chips(wrapper)[0].trigger('click')
    await swatches(wrapper)[0].trigger('click')
    await chips(wrapper)[1].trigger('click')
    await swatches(wrapper)[0].trigger('click')

    expect(wrapper.emitted('recolor')).toEqual([
      [1, PIN_COLORS[0].value],
      [2, PIN_COLORS[0].value],
    ])
  })

  it('drops the palette when the mode is closed again', async () => {
    const wrapper = mountRow()

    await pencil(wrapper).trigger('click')
    await chips(wrapper)[0].trigger('click')
    await pencil(wrapper).trigger('click')

    expect(swatches(wrapper)).toHaveLength(0)
    expect(wrapper.text()).not.toContain('Paint mode')
  })
})
