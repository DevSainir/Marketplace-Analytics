/**
 * Integration: the real router driven by the real auth guard and store.
 *
 * The guard's own spec tests it in isolation with a stubbed store. Here the
 * whole chain runs — a navigation triggers `bootstrap()`, which issues a real
 * (mocked-at-the-adapter) `/refresh`, whose outcome decides where the user
 * lands. That is the app's front door: get it wrong and either everything is
 * public or nothing is reachable.
 *
 * A memory router is used instead of the app's history router so navigations
 * are synchronous and jsdom's URL is left alone.
 */
import { createPinia, setActivePinia } from 'pinia'
import MockAdapter from 'axios-mock-adapter'
import { createMemoryHistory, createRouter } from 'vue-router'

import apiClient, { clearAccessToken } from '@/core/api/axios'
import { authRoutes, installAuthGuard } from '@/modules/auth'
import { monitoringRoutes } from '@/modules/monitoring'
import { profileRoutes } from '@/modules/profile'

let mock

const Blank = { template: '<div />' }

beforeEach(() => {
  setActivePinia(createPinia())
  mock = new MockAdapter(apiClient)
  clearAccessToken()
  localStorage.clear()
})

afterEach(() => {
  mock.restore()
})

/** Build a router over the app's real route tables with the real guard. */
function buildRouter() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: Blank },
      ...authRoutes,
      ...monitoringRoutes,
      ...profileRoutes,
    ],
  })
  installAuthGuard(router)
  return router
}

const session = () => ({
  access_token: 'access-1',
  token_type: 'bearer',
  expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
})

describe('protected routes', () => {
  it('sends a guest to /login and remembers where they were going', async () => {
    // The redirect is what makes a bookmarked deep link survive a login.
    mock.onPost('/v1/auth/refresh').reply(401)
    const router = buildRouter()

    await router.push('/monitoring')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/monitoring')
  })

  it('lets an authenticated user through', async () => {
    mock.onPost('/v1/auth/refresh').reply(200, session())
    const router = buildRouter()

    await router.push('/monitoring')

    expect(router.currentRoute.value.path).toBe('/monitoring')
  })

  it('resolves the session before the first navigation completes', async () => {
    // The guard awaits bootstrap() on purpose: without it the first paint
    // happens as a guest and every authenticated view flashes /login.
    mock.onPost('/v1/auth/refresh').reply(200, session())
    const router = buildRouter()

    await router.push('/monitoring')

    expect(mock.history.post.filter((r) => r.url === '/v1/auth/refresh')).toHaveLength(1)
  })
})

describe('guest-only routes', () => {
  it('bounces an authenticated user off /login', async () => {
    mock.onPost('/v1/auth/refresh').reply(200, session())
    const router = buildRouter()

    await router.push('/login')

    expect(router.currentRoute.value.path).toBe('/monitoring')
  })

  it('honours a safe ?redirect= when bouncing', async () => {
    mock.onPost('/v1/auth/refresh').reply(200, session())
    const router = buildRouter()

    await router.push('/login?redirect=/profile')

    expect(router.currentRoute.value.path).toBe('/profile')
  })

  it('ignores an off-site redirect target', async () => {
    // `//evil.example` is protocol-relative: a browser reads it as an absolute
    // URL, so an unsanitized redirect is an open-redirect phishing vector.
    mock.onPost('/v1/auth/refresh').reply(200, session())
    const router = buildRouter()

    await router.push('/login?redirect=//evil.example/steal')

    expect(router.currentRoute.value.path).toBe('/monitoring')
  })

  it('leaves /login reachable for a guest', async () => {
    mock.onPost('/v1/auth/refresh').reply(401)
    const router = buildRouter()

    await router.push('/login')

    expect(router.currentRoute.value.name).toBe('login')
  })
})

describe('session dying mid-use', () => {
  it('routes to /login when a request 401s and the refresh fails', async () => {
    // No hard page reload: the SPA keeps its state and the user lands back on
    // the same page after logging in.
    mock.onPost('/v1/auth/refresh').replyOnce(200, session())
    const router = buildRouter()
    await router.push('/monitoring')

    mock.onGet('/v1/monitoring/summary').reply(401)
    mock.onPost('/v1/auth/refresh').reply(401)
    await expect(apiClient.get('/v1/monitoring/summary')).rejects.toThrow()

    // The interceptor's handler pushes without awaiting, so the navigation is
    // still in flight when the rejected request settles.
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('login'))

    expect(router.currentRoute.value.query.redirect).toBe('/monitoring')
  })
})

describe('account recovery routes', () => {
  it('keeps a signed-in user off the password-reset form', async () => {
    // Same reasoning as /login: somebody who is already authenticated changes
    // their password from their profile, not from a code mailed to them.
    mock.onPost('/v1/auth/refresh').reply(200, session())
    const router = buildRouter()

    await router.push('/password-reset')

    expect(router.currentRoute.value.name).not.toBe('password-reset')
  })

  it('lets a signed-in user reach the confirmation screen', async () => {
    // The one route that must NOT be guest-only. Registration signs the account
    // in and then sends it here, so a guestOnly guard would bounce every new
    // user straight off the screen they were just handed.
    mock.onPost('/v1/auth/refresh').reply(200, session())
    const router = buildRouter()

    await router.push('/confirm-email?email=someone@example.com')

    expect(router.currentRoute.value.name).toBe('confirm-email')
  })

  it('lets a guest reach it too', async () => {
    // Confirming from a different browser than the one that registered is the
    // ordinary case — the link is in an email.
    mock.onPost('/v1/auth/refresh').reply(401)
    const router = buildRouter()

    await router.push('/confirm-email')

    expect(router.currentRoute.value.name).toBe('confirm-email')
  })

  it('lets a guest reach the password-reset form', async () => {
    mock.onPost('/v1/auth/refresh').reply(401)
    const router = buildRouter()

    await router.push('/password-reset')

    expect(router.currentRoute.value.name).toBe('password-reset')
  })
})
