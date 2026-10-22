import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import ActivationGate from '@/modules/profile/components/ActivationGate.vue'
import { fetchMembers, fetchMyInvitations, fetchOrganizationMe } from '@/modules/profile/api'
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

/** Rewritten per test — the gate reads `meta` off whatever route is current. */
let route = { meta: {} }

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return { ...actual, useRoute: () => route }
})

const ORG = { id: 'org-1', name: 'Демо' }

/** The `/v1/organizations/me` payload of a paid-up owner, unless told otherwise. */
function me(overrides = {}) {
  return {
    user_id: 'u-1',
    email: 'owner@example.com',
    role: 'owner',
    has_access: true,
    can_write: true,
    modules: ['monitoring', 'finreports'],
    organization: ORG,
    subscription: {
      started_at: '2026-08-01T00:00:00Z',
      expires_at: '2026-09-01T00:00:00Z',
      state: 'active',
      max_workspaces: null,
      max_managers: null,
    },
    ...overrides,
  }
}

/** Mount the gate over a recognisable page, with the store already answered. */
async function mountGate({ payload = me(), meta = { module: 'monitoring' } } = {}) {
  route = { meta }
  fetchOrganizationMe.mockResolvedValue(payload)
  const wrapper = mount(ActivationGate, {
    slots: { default: '<p>секретные цифры</p>' },
    global: { stubs: { RouterLink: true } },
  })
  await useMembersStore().ensureLoaded()
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('ActivationGate', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    fetchMembers.mockResolvedValue([])
    fetchMyInvitations.mockResolvedValue([])
  })

  it('lets a paid-up member through', async () => {
    const wrapper = await mountGate()

    expect(wrapper.text()).toContain('секретные цифры')
    expect(wrapper.find('.gate-card').exists()).toBe(false)
  })

  it('lets a guest with no company of their own through', async () => {
    // A dev opened a workspace to them; covering it with the key prompt would
    // hide the one thing they were let in to see.
    const wrapper = await mountGate({
      payload: me({
        role: 'user',
        organization: null,
        subscription: null,
        can_write: false,
        is_guest_only: true,
      }),
    })

    expect(wrapper.text()).toContain('секретные цифры')
    expect(wrapper.find('.gate-card').exists()).toBe(false)
  })

  it('still asks a bare registration for a key', async () => {
    const wrapper = await mountGate({
      payload: me({ role: 'user', organization: null, subscription: null, can_write: false }),
    })

    expect(wrapper.find('.gate-card').exists()).toBe(true)
  })

  it('paywalls a tenant past its grace window', async () => {
    // The whole point of the 2026-09-09 change: past grace the service is shut,
    // not read-only. The blur is cosmetic — the API refuses every request
    // behind it — but an app that renders over a wall of 403s reads as broken
    // rather than unpaid.
    const wrapper = await mountGate({
      payload: me({ has_access: false, can_write: false, subscription: null }),
    })

    expect(wrapper.text()).toContain('Подписка истекла')
    expect(wrapper.find('.gate-blurred').exists()).toBe(true)
  })

  it('paywalls the profile page too, which the activation card never covers', async () => {
    // `allowWithoutOrganization` keeps the profile legible to somebody waiting
    // for an activation key, because there is something there for them to do.
    // A lapsed tenant has nothing there that renewing does not fix first, so
    // the exemption must not extend to the paywall.
    const wrapper = await mountGate({
      payload: me({ has_access: false }),
      meta: { allowWithoutOrganization: true },
    })

    expect(wrapper.text()).toContain('Подписка истекла')
  })

  it('tells a manager who to ask instead of telling them to pay', async () => {
    // Only the owner can renew. Sending a manager to us is sending them to the
    // wrong person, and they cannot act on the answer they would get.
    const wrapper = await mountGate({
      payload: me({ role: 'manager', has_access: false }),
    })

    expect(wrapper.text()).toContain('Обратитесь к владельцу компании')
    expect(wrapper.text()).not.toContain('Напишите нам')
  })

  it('names the day the term ran out when it knows it', async () => {
    const wrapper = await mountGate({
      payload: me({
        has_access: false,
        subscription: {
          started_at: '2026-08-01T00:00:00Z',
          expires_at: '2026-09-01T00:00:00Z',
          state: 'expired',
          max_workspaces: null,
          max_managers: null,
        },
      }),
    })

    expect(wrapper.text()).toContain('1 сентября 2026')
  })

  it('does not flash a paywall before the API has answered', async () => {
    // A cold load must not accuse a paying customer of not paying. The store
    // answers "allowed" until `/me` has spoken, and the API is the gate that
    // actually decides.
    route = { meta: { module: 'monitoring' } }
    fetchOrganizationMe.mockResolvedValue(me({ has_access: false }))

    const wrapper = mount(ActivationGate, {
      slots: { default: '<p>секретные цифры</p>' },
      global: { stubs: { RouterLink: true } },
    })

    expect(wrapper.find('.gate-card').exists()).toBe(false)
  })

  it('still asks an unattached account for its activation key', async () => {
    const wrapper = await mountGate({
      payload: me({ role: 'user', organization: null, modules: [], subscription: null }),
      meta: {},
    })

    expect(wrapper.text()).toContain('Нужен ключ активации')
  })

  it('still refuses a section the manager was not granted', async () => {
    const wrapper = await mountGate({
      payload: me({ role: 'manager', modules: ['monitoring'] }),
      meta: { module: 'finreports' },
    })

    expect(wrapper.text()).toContain('Раздел недоступен')
  })
})
