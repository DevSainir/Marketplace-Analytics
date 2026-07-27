/**
 * Integration: the whole session lifecycle across axios + api + store.
 *
 * Each unit is already covered on its own. What is only visible here is the
 * seam between them — the interceptor refreshing a token that the store then
 * has to adopt, and the store's "transient failure vs dead session" rule
 * deciding whether a blip logs the user out.
 *
 * That rule is the load-bearing one: treating a 500 or a network drop as
 * "logged out" bounced people to /login during every backend deploy, when a
 * plain reload would have worked.
 */
import { createPinia, setActivePinia } from 'pinia'
import MockAdapter from 'axios-mock-adapter'

import apiClient, { clearAccessToken, setUnauthorizedHandler } from '@/core/api/axios'
import { useAuthStore } from '@/modules/auth/store'

let mock

beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  mock = new MockAdapter(apiClient)
  clearAccessToken()
  localStorage.clear()
  setUnauthorizedHandler(() => {})
})

afterEach(() => {
  mock.restore()
  vi.useRealTimers()
})

/** An access token expiring far enough out that no proactive refresh fires. */
const tokens = (accessToken = 'access-1') => ({
  access_token: accessToken,
  token_type: 'bearer',
  expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
})

describe('login', () => {
  it('authenticates and stamps the token onto subsequent requests', async () => {
    const auth = useAuthStore()
    mock.onPost('/v1/auth/login').reply(200, tokens('access-1'))
    mock
      .onGet('/v1/monitoring/summary')
      .reply((config) => [200, { seen: config.headers.Authorization }])

    const ok = await auth.login('user@example.com', 'password')
    const { data } = await apiClient.get('/v1/monitoring/summary')

    expect(ok).toBe(true)
    expect(auth.isAuthenticated).toBe(true)
    expect(data.seen).toBe('Bearer access-1')
  })

  it('surfaces the backend message on bad credentials without a session', async () => {
    const auth = useAuthStore()
    mock
      .onPost('/v1/auth/login')
      .reply(401, { error: { code: 'unauthorized', message: 'Invalid email or password.' } })

    const ok = await auth.login('user@example.com', 'wrong')

    expect(ok).toBe(false)
    expect(auth.isAuthenticated).toBe(false)
    expect(auth.error).toBe('Invalid email or password.')
  })
})

describe('bootstrap on app start', () => {
  it('turns a live refresh cookie into an authenticated session', async () => {
    const auth = useAuthStore()
    mock.onPost('/v1/auth/refresh').reply(200, tokens('bootstrapped'))

    await auth.bootstrap()

    expect(auth.status).toBe('authenticated')
  })

  it('lands on guest when the refresh cookie is rejected', async () => {
    const auth = useAuthStore()
    mock.onPost('/v1/auth/refresh').reply(401)

    await auth.bootstrap()

    expect(auth.status).toBe('guest')
  })

  it('retries a transient failure before giving up', async () => {
    // A 503 is a backend restarting mid-deploy, not an expired session:
    // logging the user out here is the bug this retry exists to prevent.
    const auth = useAuthStore()
    mock.onPost('/v1/auth/refresh').replyOnce(503)
    mock.onPost('/v1/auth/refresh').reply(200, tokens('recovered'))

    const bootstrapping = auth.bootstrap()
    await vi.advanceTimersByTimeAsync(1_500)
    await bootstrapping

    expect(auth.status).toBe('authenticated')
  })

  it('gives up as guest once the transient retries are exhausted', async () => {
    const auth = useAuthStore()
    mock.onPost('/v1/auth/refresh').reply(503)

    const bootstrapping = auth.bootstrap()
    await vi.advanceTimersByTimeAsync(10_000)
    await bootstrapping

    expect(auth.status).toBe('guest')
  })

  it('shares one refresh round-trip between concurrent callers', async () => {
    // The router guard and the views all call bootstrap() on first paint; three
    // parallel /refresh calls would rotate the cookie three times and two of
    // them would then look like token reuse to the backend's breach detector.
    const auth = useAuthStore()
    mock.onPost('/v1/auth/refresh').reply(200, tokens())

    await Promise.all([auth.bootstrap(), auth.bootstrap(), auth.bootstrap()])

    expect(mock.history.post.filter((r) => r.url === '/v1/auth/refresh')).toHaveLength(1)
  })
})

describe('expiry mid-session', () => {
  it('refreshes and retries transparently when a request 401s', async () => {
    const auth = useAuthStore()
    mock.onPost('/v1/auth/login').reply(200, tokens('stale'))
    await auth.login('user@example.com', 'password')

    mock.onGet('/v1/monitoring/summary').replyOnce(401)
    mock.onPost('/v1/auth/refresh').reply(200, tokens('rotated'))
    mock
      .onGet('/v1/monitoring/summary')
      .reply((config) => [200, { seen: config.headers.Authorization }])

    const { data } = await apiClient.get('/v1/monitoring/summary')

    expect(data.seen).toBe('Bearer rotated')
  })

  it('hands over to the unauthorized handler when the refresh also fails', async () => {
    const auth = useAuthStore()
    mock.onPost('/v1/auth/login').reply(200, tokens())
    await auth.login('user@example.com', 'password')
    let handled = false
    setUnauthorizedHandler(() => {
      handled = true
      auth.markGuest()
    })

    mock.onGet('/v1/monitoring/summary').reply(401)
    mock.onPost('/v1/auth/refresh').reply(401)

    await expect(apiClient.get('/v1/monitoring/summary')).rejects.toThrow()

    expect(handled).toBe(true)
    expect(auth.isAuthenticated).toBe(false)
  })

  it('rotates the token proactively before it expires', async () => {
    // Refreshing ~60s early keeps requests from racing the 401 interceptor,
    // which matters most on the first click after a long idle tab.
    const auth = useAuthStore()
    mock.onPost('/v1/auth/login').reply(200, {
      access_token: 'short-lived',
      token_type: 'bearer',
      expires_at: new Date(Date.now() + 90_000).toISOString(),
    })
    await auth.login('user@example.com', 'password')
    mock.onPost('/v1/auth/refresh').reply(200, tokens('proactively-rotated'))

    await vi.advanceTimersByTimeAsync(35_000)

    expect(mock.history.post.filter((r) => r.url === '/v1/auth/refresh')).toHaveLength(1)
    expect(auth.isAuthenticated).toBe(true)
  })

  it('keeps the session alive when a proactive refresh hits a blip', async () => {
    const auth = useAuthStore()
    mock.onPost('/v1/auth/login').reply(200, {
      access_token: 'short-lived',
      token_type: 'bearer',
      expires_at: new Date(Date.now() + 90_000).toISOString(),
    })
    await auth.login('user@example.com', 'password')
    mock.onPost('/v1/auth/refresh').reply(500)

    await vi.advanceTimersByTimeAsync(35_000)

    expect(auth.isAuthenticated).toBe(true)
  })
})

describe('logout', () => {
  it('drops the session and stops sending the token', async () => {
    const auth = useAuthStore()
    mock.onPost('/v1/auth/login').reply(200, tokens())
    await auth.login('user@example.com', 'password')
    mock.onPost('/v1/auth/logout').reply(204)
    mock
      .onGet('/v1/monitoring/summary')
      .reply((config) => [200, { seen: config.headers.Authorization ?? null }])

    await auth.logout()
    const { data } = await apiClient.get('/v1/monitoring/summary')

    expect(auth.isAuthenticated).toBe(false)
    expect(data.seen).toBeNull()
    expect(localStorage.getItem('auth:email')).toBeNull()
  })

  it('still ends the local session when the server call fails', async () => {
    // Logout is idempotent server-side; leaving the user "logged in" locally
    // because the network dropped is the worst of both worlds.
    const auth = useAuthStore()
    mock.onPost('/v1/auth/login').reply(200, tokens())
    await auth.login('user@example.com', 'password')
    mock.onPost('/v1/auth/logout').networkError()

    await auth.logout()

    expect(auth.isAuthenticated).toBe(false)
  })
})
