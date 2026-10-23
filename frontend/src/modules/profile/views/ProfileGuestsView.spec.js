import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import ProfileGuestsView from '@/modules/profile/views/ProfileGuestsView.vue'
import {
  fetchGrantableWorkspaces,
  fetchGuestGrants,
  fetchMembers,
  fetchMyInvitations,
  fetchOrganizationMe,
  grantGuest,
  revokeGuest,
} from '@/modules/profile/api'

vi.mock('@/modules/profile/api', () => ({
  acceptInvitation: vi.fn(),
  activateOrganization: vi.fn(),
  createInvitation: vi.fn(),
  fetchAuditLog: vi.fn(),
  fetchGrantableWorkspaces: vi.fn(),
  fetchGuestGrants: vi.fn(),
  fetchInvitations: vi.fn(),
  fetchMembers: vi.fn(),
  fetchMyInvitations: vi.fn(),
  fetchOrganizationMe: vi.fn(),
  grantGuest: vi.fn(),
  removeMember: vi.fn(),
  revokeGuest: vi.fn(),
  revokeInvitation: vi.fn(),
  updateMemberAccess: vi.fn(),
}))

/**
 * "Access": a dev opens another company's workspace to an account, read-only.
 *
 * The API is the gate (`DevAccess`); what is pinned here is that the form sends
 * what was chosen, the list follows what the server holds, and nobody but a
 * dev is shown the form or made to fire requests that will be refused.
 */
const GRANT = {
  id: 'g-1',
  email: 'guest@example.com',
  workspace_id: 'ws-via',
  workspace_name: 'NEVA',
  created_at: '2026-10-08T10:00:00Z',
}

function me(role) {
  return {
    user_id: 'u-1',
    email: 'dev@example.com',
    role,
    has_access: true,
    can_write: true,
    modules: [],
    organization: { id: 'org-1', name: 'Demo' },
    subscription: null,
  }
}

async function mountView(role = 'dev') {
  fetchOrganizationMe.mockResolvedValue(me(role))
  const wrapper = mount(ProfileGuestsView)
  await flushPromises()
  return wrapper
}

describe('ProfileGuestsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    fetchMembers.mockResolvedValue([])
    fetchMyInvitations.mockResolvedValue([])
    fetchGuestGrants.mockResolvedValue([GRANT])
    fetchGrantableWorkspaces.mockResolvedValue([
      { id: 'ws-main', name: 'Demo' },
      { id: 'ws-via', name: 'NEVA' },
    ])
  })

  it('lists the standing grants for a dev', async () => {
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('guest@example.com')
    expect(wrapper.text()).toContain('NEVA')
  })

  it('sends the typed email and the chosen workspace', async () => {
    const wrapper = await mountView()
    grantGuest.mockResolvedValue(GRANT)

    await wrapper.find('input[type="email"]').setValue(' someone@example.com ')
    await wrapper.find('select').setValue('Demo')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(grantGuest).toHaveBeenCalledWith({
      email: 'someone@example.com',
      workspaceName: 'Demo',
    })
  })

  it('shows why a grant was refused', async () => {
    const wrapper = await mountView()
    grantGuest.mockRejectedValue({
      response: { data: { detail: 'No account with this email.' } },
    })

    await wrapper.find('input[type="email"]').setValue('nobody@example.com')
    await wrapper.find('select').setValue('NEVA')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('No account with this email.')
  })

  it('drops a closed grant from the list', async () => {
    const wrapper = await mountView()
    revokeGuest.mockResolvedValue()

    await wrapper.find('.ui-btn--danger').trigger('click')
    await flushPromises()

    expect(revokeGuest).toHaveBeenCalledWith('g-1')
    expect(wrapper.text()).not.toContain('guest@example.com')
  })

  it('shows a non-dev a refusal and asks the API nothing', async () => {
    const wrapper = await mountView('owner')

    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.text()).toContain('Only a developer')
    expect(fetchGuestGrants).not.toHaveBeenCalled()
  })
})
