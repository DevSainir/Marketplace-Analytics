import { createPinia, setActivePinia } from 'pinia'

import {
  activateOrganization,
  fetchMembers,
  fetchMyInvitations,
  fetchOrganizationMe,
} from '@/modules/profile/api'
import { useMembersStore } from '@/modules/profile/membersStore'

vi.mock('@/modules/profile/api', () => ({
  acceptInvitation: vi.fn(),
  activateOrganization: vi.fn(),
  createInvitation: vi.fn(),
  fetchMembers: vi.fn(),
  fetchMyInvitations: vi.fn(),
  fetchOrganizationMe: vi.fn(),
  updateMemberAccess: vi.fn(),
}))

const ORG = { id: 'org-1', name: 'Demo' }

/** The `/v1/organizations/me` payload, defaulting to a fresh unattached account. */
function me(overrides = {}) {
  return {
    user_id: 'u-1',
    email: 'new@example.com',
    role: 'user',
    can_write: false,
    organization: null,
    subscription: null,
    ...overrides,
  }
}

describe('membersStore — the account that has not been let in yet', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    fetchMembers.mockResolvedValue([])
    // Asked for only when the account has no organisation, which most of these
    // cases are.
    fetchMyInvitations.mockResolvedValue([])
  })

  it('does not claim the account is blocked before it has asked', async () => {
    // Otherwise every member sees the activation overlay flash on a cold load,
    // which is worse than the state it exists to explain.
    const store = useMembersStore()

    expect(store.hasOrganization).toBe(true)
  })

  it('reports the blocked state once the API has answered', async () => {
    fetchOrganizationMe.mockResolvedValue(me())
    const store = useMembersStore()

    await store.ensureLoaded()

    expect(store.hasOrganization).toBe(false)
  })

  it('leaves a member who does belong alone', async () => {
    fetchOrganizationMe.mockResolvedValue(me({ role: 'owner', organization: ORG }))
    const store = useMembersStore()

    await store.ensureLoaded()

    expect(store.hasOrganization).toBe(true)
  })

  it('lifts the gate when a code is redeemed, and re-reads everything', async () => {
    // The role, the module grants and the workspace list are all downstream of
    // the answer that just changed, so a patch would leave them stale.
    fetchOrganizationMe.mockResolvedValueOnce(me())
    const store = useMembersStore()
    await store.ensureLoaded()
    expect(store.hasOrganization).toBe(false)

    activateOrganization.mockResolvedValue(ORG)
    fetchOrganizationMe.mockResolvedValueOnce(me({ role: 'owner', organization: ORG }))

    const ok = await store.activate('GOOD-CODE')

    expect(ok).toBe(true)
    expect(store.hasOrganization).toBe(true)
    expect(store.role).toBe('owner')
    expect(fetchOrganizationMe).toHaveBeenCalledTimes(2)
  })

  it('keeps the gate up and explains why when the code is refused', async () => {
    fetchOrganizationMe.mockResolvedValue(me())
    const store = useMembersStore()
    await store.ensureLoaded()

    activateOrganization.mockRejectedValue({
      isAxiosError: true,
      response: { status: 403, data: { error: { message: 'Invalid activation code.' } } },
    })

    const ok = await store.activate('WRONG')

    expect(ok).toBe(false)
    expect(store.hasOrganization).toBe(false)
    expect(store.error).toBe('Invalid activation code.')
    expect(store.saving).toBeNull()
  })
})
