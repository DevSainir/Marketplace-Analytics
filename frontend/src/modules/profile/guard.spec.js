import { useAuthStore } from '@/modules/auth'
import { installInternalGuard } from '@/modules/profile/guard'
import { useMembersStore } from '@/modules/profile/membersStore'

vi.mock('@/modules/auth', () => ({ useAuthStore: vi.fn() }))
vi.mock('@/modules/profile/membersStore', () => ({ useMembersStore: vi.fn() }))
vi.mock('@/modules/profile/store', () => ({ useWorkspaceStore: vi.fn() }))

describe('installInternalGuard', () => {
  let router

  beforeEach(() => {
    vi.clearAllMocks()
    router = { beforeEach: vi.fn() }
  })

  /** Install against fake stores and return the registered beforeEach handler. */
  function install({ authenticated = true, internalFeatures = false, loadFails = false } = {}) {
    useAuthStore.mockReturnValue({ isAuthenticated: authenticated })
    useMembersStore.mockReturnValue({
      internalFeatures,
      ensureLoaded: loadFails
        ? vi.fn().mockRejectedValue(new Error('boom'))
        : vi.fn().mockResolvedValue(undefined),
    })
    installInternalGuard(router)
    return router.beforeEach.mock.calls[0][0]
  }


  it('lets an ordinary route through without asking who the viewer is', async () => {
    const guard = install()
    const members = useMembersStore()

    expect(await guard({ path: '/monitoring', meta: { requiresAuth: true } })).toBe(true)
    expect(members.ensureLoaded).not.toHaveBeenCalled()
  })

  it('admits a viewer the API counts as one of us', async () => {
    const guard = install({ internalFeatures: true })

    expect(await guard(INTERNAL_ROUTE)).toBe(true)
  })

  it('answers not-found for a customer rather than redirecting them', async () => {
    // A redirect to the dashboard would confirm the section exists. The backend
    // phrases its own refusal as "Раздел недоступен." for the same reason.
    const guard = install({ internalFeatures: false })

    expect(await guard(INTERNAL_ROUTE)).toMatchObject({ name: 'not-found', replace: true })
  })

  it('fails CLOSED when it cannot find out who the viewer is', async () => {
    // Every other bootstrap in this app lets navigation continue on failure and
    // lets the view report the error. Not this one: an unanswered question
    // about identity must never resolve to "one of us".
    const guard = install({ internalFeatures: false, loadFails: true })

    expect(await guard(INTERNAL_ROUTE)).toMatchObject({ name: 'not-found' })
  })

  it('leaves an unauthenticated visitor to the auth guard', async () => {
    const guard = install({ authenticated: false })

    expect(await guard(INTERNAL_ROUTE)).toBe(true)
  })
})
