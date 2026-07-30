import { mount } from '@vue/test-utils'

import RefreshAllSkusButton from '@/modules/monitoring/components/RefreshAllSkusButton.vue'

describe('RefreshAllSkusButton', () => {
  it('emits refresh when clicked', async () => {
    const wrapper = mount(RefreshAllSkusButton)

    await wrapper.find('button').trigger('click')

    expect(wrapper.emitted('refresh')).toHaveLength(1)
  })

  it('disables itself and swaps the label while a refresh is in flight', () => {
    // The guard against a double-enqueue is visual as well as in the store: a
    // clickable button mid-run invites the user to fire a second harvest.
    const wrapper = mount(RefreshAllSkusButton, { props: { refreshing: true } })

    expect(wrapper.find('button').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('Обновляем все SKU')
  })

  it('shows the error message and hides the warning when both are set', () => {
    // Error wins over warning: a failure the user must act on must not be
    // hidden behind a softer "WB withheld some data" note.
    const wrapper = mount(RefreshAllSkusButton, {
      props: { error: 'Что-то пошло не так', warning: 'WB не отдал остатки' },
    })

    expect(wrapper.find('[role="alert"]').text()).toBe('Что-то пошло не так')
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })
})
