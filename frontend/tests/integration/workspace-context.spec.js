/**
 * Integration: workspace selection → axios header → backend scoping.
 *
 * The tenancy header is set in one module (`core/api/axios`) and decided in
 * another (`modules/profile/store`), with `localStorage` in between. Every
 * workspace-scoped request depends on that chain being intact, and a break in
 * it does not throw — it silently reads another tenant's data or 400s.
 *
 * The recovery path matters just as much: a workspace deleted while a client
 * still had it selected must not leave the app permanently 404-ing.
 */
import { createPinia, setActivePinia } from 'pinia'
import MockAdapter from 'axios-mock-adapter'

import apiClient, { getWorkspaceId, setWorkspaceId } from '@/core/api/axios'
import { useWorkspaceStore } from '@/modules/profile/store'

let mock

const PRIMARY = {
  id: 'aaaaaaaa-0000-7000-8000-000000000001',
  name: 'Demo Shop',
  is_primary: true,
}
const SECOND = { id: 'bbbbbbbb-0000-7000-8000-000000000002', name: 'Second LLC', is_primary: false }

beforeEach(() => {
  setActivePinia(createPinia())
  mock = new MockAdapter(apiClient)
  localStorage.clear()
  setWorkspaceId(null)
})

afterEach(() => {
  mock.restore()
})

function respondWith(workspaces, { role = 'user' } = {}) {
  mock
    .onGet('/v1/auth/me')
    .reply(200, { id: 'u1', email: 'user@example.com', role, is_active: true })
  mock.onGet('/v1/workspaces').reply(200, { items: workspaces })
}

describe('selection', () => {
  it('adopts the first workspace when none is stored', async () => {
    const store = useWorkspaceStore()
    respondWith([PRIMARY, SECOND])

    await store.ensureLoaded()

    expect(store.currentWorkspaceId).toBe(PRIMARY.id)
  })

  it('keeps a stored selection that is still valid', async () => {
    // Switching workspace must survive a reload; silently resetting to the
    // first one would make the switcher feel broken.
    setWorkspaceId(SECOND.id)
    const store = useWorkspaceStore()
    respondWith([PRIMARY, SECOND])

    await store.ensureLoaded()

    expect(store.currentWorkspaceId).toBe(SECOND.id)
  })

  it('recovers when the stored workspace no longer exists', async () => {
    // A workspace deleted by a teammate would otherwise leave this client
    // sending a dead id on every request and 404-ing forever.
    setWorkspaceId('cccccccc-0000-7000-8000-000000000003')
    const store = useWorkspaceStore()
    respondWith([PRIMARY])

    await store.ensureLoaded()

    expect(store.currentWorkspaceId).toBe(PRIMARY.id)
  })

  it('selects nothing when the account has no workspaces', async () => {
    const store = useWorkspaceStore()
    respondWith([])

    await store.ensureLoaded()

    expect(store.currentWorkspaceId).toBeNull()
    expect(getWorkspaceId()).toBeNull()
  })
})

describe('header propagation', () => {
  it('stamps the active workspace onto every request', async () => {
    const store = useWorkspaceStore()
    respondWith([PRIMARY, SECOND])
    await store.ensureLoaded()
    mock
      .onGet('/v1/monitoring/summary')
      .reply((config) => [200, { ws: config.headers['X-Workspace-Id'] }])

    const { data } = await apiClient.get('/v1/monitoring/summary')

    expect(data.ws).toBe(PRIMARY.id)
  })

  it('switching workspace changes the header on the next request', async () => {
    const store = useWorkspaceStore()
    respondWith([PRIMARY, SECOND])
    await store.ensureLoaded()
    mock
      .onGet('/v1/monitoring/summary')
      .reply((config) => [200, { ws: config.headers['X-Workspace-Id'] }])

    store.select(SECOND.id)
    const { data } = await apiClient.get('/v1/monitoring/summary')

    expect(data.ws).toBe(SECOND.id)
  })

  it('persists the selection so a reload keeps the same tenant', async () => {
    const store = useWorkspaceStore()
    respondWith([PRIMARY, SECOND])
    await store.ensureLoaded()

    store.select(SECOND.id)

    expect(localStorage.getItem('workspace:id')).toBe(SECOND.id)
  })

  it('sends no workspace header when nothing is selected', async () => {
    // Better a clean 400 from the backend than a request scoped to "null",
    // which a permissive query could read as "every tenant".
    mock
      .onGet('/v1/monitoring/summary')
      .reply((config) => [200, { ws: config.headers['X-Workspace-Id'] ?? null }])

    const { data } = await apiClient.get('/v1/monitoring/summary')

    expect(data.ws).toBeNull()
  })
})

describe('profile', () => {
  it('unlocks the admin panel only for the dev role', async () => {
    const store = useWorkspaceStore()
    respondWith([PRIMARY], { role: 'dev' })

    await store.ensureLoaded()

    expect(store.isDev).toBe(true)
  })

  it('keeps the admin panel hidden for a regular account', async () => {
    const store = useWorkspaceStore()
    respondWith([PRIMARY], { role: 'user' })

    await store.ensureLoaded()

    expect(store.isDev).toBe(false)
  })

  it('loads the context once and shares it between callers', async () => {
    const store = useWorkspaceStore()
    respondWith([PRIMARY])

    await Promise.all([store.ensureLoaded(), store.ensureLoaded(), store.ensureLoaded()])

    expect(mock.history.get.filter((r) => r.url === '/v1/workspaces')).toHaveLength(1)
  })

  it('lets the next navigation retry after a failed load', async () => {
    // Caching the rejected promise would strand the app on an error screen
    // until a full reload.
    const store = useWorkspaceStore()
    mock.onGet('/v1/auth/me').replyOnce(500)
    mock.onGet('/v1/workspaces').replyOnce(500)

    await expect(store.ensureLoaded()).rejects.toThrow()
    respondWith([PRIMARY])
    await store.ensureLoaded()

    expect(store.currentWorkspaceId).toBe(PRIMARY.id)
  })
})
