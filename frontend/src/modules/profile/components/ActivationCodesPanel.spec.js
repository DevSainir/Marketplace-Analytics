import { flushPromises, mount } from '@vue/test-utils'

import ActivationCodesPanel from '@/modules/profile/components/ActivationCodesPanel.vue'
import { createActivationCode } from '@/modules/profile/api'

vi.mock('@/modules/profile/api', () => ({ createActivationCode: vi.fn() }))

/**
 * Issuing an activation key from the profile.
 *
 * The defaults are the commercial promise: "a key for N days" means N days of
 * service, and everything not typed is unlimited. A form that sent 30 where 14
 * was meant, or a cleared field as 0 instead of "no limit", would sell
 * something other than what was agreed.
 */
const ISSUED = {
  id: 'id-1',
  code: 'the-key',
  note: '',
  expires_at: null,
  subscription_days: 14,
  max_workspaces: null,
  max_managers: null,
}

beforeEach(() => {
  createActivationCode.mockReset()
  createActivationCode.mockResolvedValue(ISSUED)
})

describe('ActivationCodesPanel', () => {
  it('sends 14 days of service and nothing else bounded by default', async () => {
    const wrapper = mount(ActivationCodesPanel)

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(createActivationCode).toHaveBeenCalledWith({
      note: '',
      subscriptionDays: 14,
      validForDays: null,
      maxWorkspaces: null,
      maxManagers: null,
    })
  })

  it('sends the limits that were typed', async () => {
    const wrapper = mount(ActivationCodesPanel)
    const inputs = wrapper.findAll('input[type="number"]')

    await inputs[0].setValue(7)
    await inputs[1].setValue(30)
    await inputs[2].setValue(2)
    await inputs[3].setValue(5)
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(createActivationCode).toHaveBeenCalledWith(
      expect.objectContaining({
        subscriptionDays: 7,
        validForDays: 30,
        maxWorkspaces: 2,
        maxManagers: 5,
      }),
    )
  })

  it('treats a cleared limit as unlimited, not zero', async () => {
    const wrapper = mount(ActivationCodesPanel)
    const workspaces = wrapper.findAll('input[type="number"]')[2]

    await workspaces.setValue(3)
    await workspaces.setValue('')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(createActivationCode.mock.calls[0][0].maxWorkspaces).toBeNull()
  })

  it('shows the issued key once it is created', async () => {
    const wrapper = mount(ActivationCodesPanel)

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('code').text()).toBe('the-key')
    expect(wrapper.text()).toContain('no expiry')
  })
})
