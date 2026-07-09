import { createPinia, setActivePinia } from 'pinia'

import { loginUser, logoutUser, refreshSession, registerUser } from '@/modules/auth/api'
import { useAuthStore } from '@/modules/auth/store'

vi.mock('@/modules/auth/api', () => ({
  loginUser: vi.fn(),
  logoutUser: vi.fn(),
  refreshSession: vi.fn(),
  registerUser: vi.fn(),
}))

const TOKENS = { access_token: 'jwt', expires_at: '2026-07-08T12:00:00Z' }

let store

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  store = useAuthStore()
  vi.clearAllMocks()
})

describe('login', () => {
  it('marks the session authenticated and remembers the email', async () => {
    loginUser.mockResolvedValue(TOKENS)

    const ok = await store.login('manager@example.com', 'secret-password')

    expect(ok).toBe(true)
    expect(store.isAuthenticated).toBe(true)
    expect(store.userEmail).toBe('manager@example.com')
    expect(localStorage.getItem('auth:email')).toBe('manager@example.com')
  })

  it('surfaces backend errors and stays unauthenticated', async () => {
    loginUser.mockRejectedValue({ response: { data: { detail: 'Invalid credentials.' } } })

    const ok = await store.login('manager@example.com', 'wrong')

    expect(ok).toBe(false)
    expect(store.isAuthenticated).toBe(false)
    expect(store.error).toBe('Invalid credentials.')
  })
})

describe('register', () => {
  it('creates the account and logs straight in', async () => {
    registerUser.mockResolvedValue({ id: 'u1', email: 'new@example.com' })
    loginUser.mockResolvedValue(TOKENS)

    const ok = await store.register('new@example.com', 'secret-password')

    expect(ok).toBe(true)
    expect(loginUser).toHaveBeenCalledWith({
      email: 'new@example.com',
      password: 'secret-password',
    })
    expect(store.isAuthenticated).toBe(true)
  })

  it('stops on a registration conflict without attempting login', async () => {
    registerUser.mockRejectedValue({
      response: { data: { error: { code: 'conflict', message: 'Email already registered.' } } },
    })

    const ok = await store.register('dup@example.com', 'secret-password')

    expect(ok).toBe(false)
    expect(loginUser).not.toHaveBeenCalled()
    expect(store.error).toBe('Email already registered.')
  })
})

describe('bootstrap', () => {
  it('restores the session from the refresh cookie', async () => {
    refreshSession.mockResolvedValue(TOKENS)

    await store.bootstrap()

    expect(store.isAuthenticated).toBe(true)
  })

  it('falls back to guest when the cookie is absent or dead', async () => {
    refreshSession.mockRejectedValue(new Error('401'))

    await store.bootstrap()

    expect(store.status).toBe('guest')
    expect(store.isAuthenticated).toBe(false)
  })

  it('resolves the session only once', async () => {
    refreshSession.mockResolvedValue(TOKENS)

    await Promise.all([store.bootstrap(), store.bootstrap()])
    await store.bootstrap()

    expect(refreshSession).toHaveBeenCalledTimes(1)
  })
})

describe('logout', () => {
  it('drops the session locally even if the server call fails', async () => {
    loginUser.mockResolvedValue(TOKENS)
    await store.login('manager@example.com', 'secret-password')
    logoutUser.mockRejectedValue(new Error('network down'))

    await store.logout()

    expect(store.status).toBe('guest')
    expect(store.userEmail).toBeNull()
    expect(localStorage.getItem('auth:email')).toBeNull()
  })
})
