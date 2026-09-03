import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import IssuedInvitationList from '@/modules/profile/components/IssuedInvitationList.vue'
import { useMembersStore } from '@/modules/profile/membersStore'

vi.mock('@/modules/profile/api', () => ({
  acceptInvitation: vi.fn(),
  activateOrganization: vi.fn(),
  createInvitation: vi.fn(),
  fetchIssuedInvitations: vi.fn(),
  fetchMembers: vi.fn(),
  fetchMyInvitations: vi.fn(),
  fetchOrganizationMe: vi.fn(),
  revokeInvitation: vi.fn(),
  updateMemberAccess: vi.fn(),
}))

const DAY = 86_400_000

function invitation(overrides = {}) {
  return {
    id: 'inv-1',
    email: 'manager@example.com',
    status: 'pending',
    expires_at: new Date(Date.now() + 7 * DAY).toISOString(),
    ...overrides,
  }
}

function mountWith(issued) {
  setActivePinia(createPinia())
  const store = useMembersStore()
  store.issued = issued
  return { wrapper: mount(IssuedInvitationList), store }
}

describe('IssuedInvitationList', () => {
  beforeEach(() => vi.clearAllMocks())

  it('counts the links that still work', () => {
    // The number an owner actually needs: pressing «Пригласить» three times
    // leaves three working ways into the company, and nothing supersedes
    // anything.
    const { wrapper } = mountWith([
      invitation({ id: 'a' }),
      invitation({ id: 'b' }),
      invitation({ id: 'c', status: 'accepted' }),
      invitation({ id: 'd', status: 'expired' }),
    ])

    expect(wrapper.text()).toContain('Действующих ссылок: 2')
  })

  it('offers revoke ONLY for a live invitation', () => {
    // An accepted one is a member now — the API answers 409 rather than
    // removing them — and revoking something already expired is noise.
    const { wrapper } = mountWith([
      invitation({ id: 'live' }),
      invitation({ id: 'gone', status: 'accepted' }),
      invitation({ id: 'old', status: 'expired' }),
    ])

    expect(wrapper.findAll('button')).toHaveLength(1)
  })

  it('withdraws the row it was pressed on', async () => {
    const { wrapper, store } = mountWith([invitation({ id: 'target' })])
    store.revokeInvite = vi.fn()

    await wrapper.find('button').trigger('click')

    expect(store.revokeInvite).toHaveBeenCalledWith('target')
  })

  it('never renders a token, because it is never sent one', () => {
    // The value exists once, in the response that created it. A list that
    // could show it again would mean the server had kept it.
    const { wrapper } = mountWith([invitation({ token: 'should-not-be-here' })])

    expect(wrapper.text()).not.toContain('should-not-be-here')
  })

  it('says so plainly when nothing is outstanding', () => {
    const { wrapper } = mountWith([invitation({ status: 'revoked' })])

    expect(wrapper.text()).toContain('Действующих ссылок нет')
  })
})
