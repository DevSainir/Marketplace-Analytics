import { setUnauthorizedHandler } from '@/core/api/axios'
import { installAuthGuard, safeRedirect } from '@/modules/auth/guard'
import { useAuthStore } from '@/modules/auth/store'

vi.mock('@/core/api/axios', () => ({ setUnauthorizedHandler: vi.fn() }))
vi.mock('@/modules/auth/store', () => ({ useAuthStore: vi.fn() }))

describe('safeRedirect', () => {
  it('accepts same-app absolute paths', () => {
    expect(safeRedirect('/monitoring?sku=123')).toBe('/monitoring?sku=123')
  })

  it('rejects external and protocol-relative URLs', () => {
    expect(safeRedirect('https://evil.example')).toBe('/monitoring')
    expect(safeRedirect('//evil.example')).toBe('/monitoring')
  })

  it('rejects non-string values from the query', () => {
    expect(safeRedirect(undefined)).toBe('/monitoring')
    expect(safeRedirect(['/a', '/b'])).toBe('/monitoring')
  })
})

describe('installAuthGuard', () => {
  let router

  beforeEach(() => {
    vi.clearAllMocks()
    router = {
      beforeEach: vi.fn(),
      push: vi.fn(),
      currentRoute: { value: { name: 'home', fullPath: '/' } },
    }
  })

  /** Install the guard against a fake store and return the beforeEach handler. */
  function installWithAuth(auth) {
    useAuthStore.mockReturnValue({ bootstrap: vi.fn().mockResolvedValue(undefined), ...auth })
    installAuthGuard(router)
    return router.beforeEach.mock.calls[0][0]
  }

  it('redirects unauthenticated users off requiresAuth routes, preserving the target', async () => {
    const guard = installWithAuth({ isAuthenticated: false })

    const result = await guard({
      meta: { requiresAuth: true },
      fullPath: '/monitoring?sku=123',
      query: {},
    })

    expect(result).toEqual({ name: 'login', query: { redirect: '/monitoring?sku=123' } })
  })

  it('lets authenticated users through requiresAuth routes', async () => {
    const guard = installWithAuth({ isAuthenticated: true })

    const result = await guard({ meta: { requiresAuth: true }, fullPath: '/monitoring', query: {} })

    expect(result).toBe(true)
  })

  it('bounces authenticated users off guestOnly routes to the sanitized redirect', async () => {
    const guard = installWithAuth({ isAuthenticated: true })

    await expect(
      guard({
        meta: { guestOnly: true },
        fullPath: '/login',
        query: { redirect: '/monitoring?sku=1' },
      }),
    ).resolves.toBe('/monitoring?sku=1')
    await expect(
      guard({
        meta: { guestOnly: true },
        fullPath: '/login',
        query: { redirect: '//evil.example' },
      }),
    ).resolves.toBe('/monitoring')
  })

  it('ignores routes without auth meta', async () => {
    const guard = installWithAuth({ isAuthenticated: false })

    const result = await guard({ meta: {}, fullPath: '/', query: {} })

    expect(result).toBe(true)
  })

  it('awaits bootstrap before reading the session state', async () => {
    // The session only becomes authenticated once bootstrap resolves; a guard
    // that forgets to await would bounce this navigation to /login.
    const auth = { isAuthenticated: false }
    auth.bootstrap = vi.fn(async () => {
      auth.isAuthenticated = true
    })
    // The live object (no spread copy): the guard must observe the mutation.
    useAuthStore.mockReturnValue(auth)
    installAuthGuard(router)
    const guard = router.beforeEach.mock.calls[0][0]

    const result = await guard({ meta: { requiresAuth: true }, fullPath: '/monitoring', query: {} })

    expect(auth.bootstrap).toHaveBeenCalledTimes(1)
    expect(result).toBe(true)
  })

  it('registers the router-aware unauthorized handler', () => {
    installWithAuth({ isAuthenticated: false, markGuest: vi.fn() })

    expect(setUnauthorizedHandler).toHaveBeenCalledTimes(1)

    const handler = setUnauthorizedHandler.mock.calls[0][0]
    router.currentRoute.value = { name: 'monitoring', fullPath: '/monitoring?sku=1' }
    handler()

    expect(router.push).toHaveBeenCalledWith({
      name: 'login',
      query: { redirect: '/monitoring?sku=1' },
    })
  })
})
