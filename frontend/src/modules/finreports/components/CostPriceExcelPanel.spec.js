import { mount } from '@vue/test-utils'

import CostPriceExcelPanel from '@/modules/finreports/components/CostPriceExcelPanel.vue'

function mountPanel(props = {}) {
  return mount(CostPriceExcelPanel, {
    props: { busy: false, result: null, currency: 'KGS', ...props },
  })
}

describe('CostPriceExcelPanel', () => {
  it('emits export when the download button is clicked', async () => {
    const wrapper = mountPanel()

    await wrapper.find('button').trigger('click')

    expect(wrapper.emitted('export')).toHaveLength(1)
  })

  it('emits import with the chosen file', async () => {
    const wrapper = mountPanel()
    const file = new File(['x'], 'costs.xlsx')
    const input = wrapper.find('input[type="file"]')
    // jsdom won't let us set input.files directly; stub the getter.
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })

    await input.trigger('change')

    expect(wrapper.emitted('import')[0]).toEqual([file])
  })

  it('renders the applied/skipped counts and each unapplied row', () => {
    const wrapper = mountPanel({
      result: {
        applied: 3,
        skipped: 2,
        issues: [{ row: 5, nm_id: 999, reason: 'The SKU has never sold.' }],
      },
    })

    const text = wrapper.text()
    expect(text).toContain('3')
    expect(text).toContain('row 5')
    expect(text).toContain('WB ID 999')
    expect(text).toContain('The SKU has never sold.')
  })

  it('disables the controls while a transfer is in flight', () => {
    const wrapper = mountPanel({ busy: true })

    expect(wrapper.find('button').attributes('disabled')).toBeDefined()
    expect(wrapper.find('input[type="file"]').attributes('disabled')).toBeDefined()
  })
})
