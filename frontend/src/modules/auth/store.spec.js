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
    refreshSession.mockRejectedValue({ response: { status: 401 } })

    await store.bootstrap()

    expect(store.status).toBe('guest')
    expect(store.isAuthenticated).toBe(false)
    expect(refreshSession).toHaveBeenCalledTimes(1) // an explicit 401 is final: no retries
  })

  it('retries a transient failure instead of dropping to guest', async () => {
    vi.useFakeTimers()
    refreshSession
      .mockRejectedValueOnce({ response: { status: 429 } })
      .mockResolvedValueOnce(TOKENS)

    const pending = store.bootstrap()
    await vi.advanceTimersByTimeAsync(1_000)
    await pending

    expect(store.isAuthenticated).toBe(true)
    expect(refreshSession).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
  })

  it('gives up on a persistent transient failure after bounded retries', async () => {
    // The ladder covers a deploy's api restart (~30s) rather than the ~10s it
    // used to: a swap shorter than the ladder no longer throws a logged-in user
    // onto /login. It is still bounded — a backend that is genuinely gone ends as
    // guest instead of spinning forever.
    vi.useFakeTimers()
    refreshSession.mockRejectedValue(new Error('network down'))

    const pending = store.bootstrap()
    await vi.advanceTimersByTimeAsync(30_000)
    await pending

    expect(store.status).toBe('guest')
    expect(refreshSession).toHaveBeenCalledTimes(5) // initial try + four retries
    vi.useRealTimers()
  })

  it('resolves the session only once', async () => {
    refreshSession.mockResolvedValue(TOKENS)

    await Promise.all([store.bootstrap(), store.bootstrap()])
    await store.bootstrap()

    expect(refreshSession).toHaveBeenCalledTimes(1)
  })
})

describe('proactive refresh', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  /** Tokens expiring `minutes` from the (fake) current time. */
  function tokensExpiringIn(minutes) {
    return {
      access_token: 'jwt',
      expires_at: new Date(Date.now() + minutes * 60_000).toISOString(),
    }
  }

  it('rotates the token ~60s before expiry', async () => {
    vi.useFakeTimers()
    loginUser.mockResolvedValue(tokensExpiringIn(5))
    refreshSession.mockResolvedValue(tokensExpiringIn(10))

    await store.login('manager@example.com', 'secret-password')

    // One second before the refresh point: nothing yet.
    await vi.advanceTimersByTimeAsync(4 * 60_000 - 1_000)
    expect(refreshSession).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1_000)
    expect(refreshSession).toHaveBeenCalledTimes(1)
    expect(store.isAuthenticated).toBe(true)
  })

  it('reschedules after each rotation', async () => {
    vi.useFakeTimers()
    loginUser.mockResolvedValue(tokensExpiringIn(5))
    refreshSession.mockImplementation(async () => tokensExpiringIn(5))

    await store.login('manager@example.com', 'secret-password')
    await vi.advanceTimersByTimeAsync(8 * 60_000)

    expect(refreshSession).toHaveBeenCalledTimes(2)
  })

  it('drops the session when the refresh cookie is rejected', async () => {
    vi.useFakeTimers()
    loginUser.mockResolvedValue(tokensExpiringIn(5))
    refreshSession.mockRejectedValue({ response: { status: 401 } })

    await store.login('manager@example.com', 'secret-password')
    await vi.advanceTimersByTimeAsync(5 * 60_000)

    expect(store.status).toBe('guest')
  })

  it('keeps the session and retries on a transient refresh failure', async () => {
    vi.useFakeTimers()
    loginUser.mockResolvedValue(tokensExpiringIn(5))
    refreshSession
      .mockRejectedValueOnce({ response: { status: 429 } })
      .mockResolvedValueOnce(tokensExpiringIn(15))

    await store.login('manager@example.com', 'secret-password')
    // First attempt fires ~60s before expiry and fails transiently...
    await vi.advanceTimersByTimeAsync(4 * 60_000)
    expect(store.isAuthenticated).toBe(true)
    expect(refreshSession).toHaveBeenCalledTimes(1)

    // ...the retry ~20s later succeeds and the session survives.
    await vi.advanceTimersByTimeAsync(21_000)
    expect(refreshSession).toHaveBeenCalledTimes(2)
    expect(store.isAuthenticated).toBe(true)
  })

  it('cancels the timer on logout', async () => {
    vi.useFakeTimers()
    loginUser.mockResolvedValue(tokensExpiringIn(5))
    logoutUser.mockResolvedValue()

    await store.login('manager@example.com', 'secret-password')
    await store.logout()
    await vi.advanceTimersByTimeAsync(10 * 60_000)

    expect(refreshSession).not.toHaveBeenCalled()
  })

  it('schedules nothing for a non-parsable expiry', async () => {
    vi.useFakeTimers()
    loginUser.mockResolvedValue({ access_token: 'jwt', expires_at: 'not-a-date' })

    await store.login('manager@example.com', 'secret-password')
    await vi.advanceTimersByTimeAsync(60 * 60_000)

    expect(store.isAuthenticated).toBe(true)
    expect(refreshSession).not.toHaveBeenCalled()
  })
})

describe('clearError', () => {
  it('dismisses the last error without touching the session', async () => {
    loginUser.mockRejectedValue({ response: { data: { detail: 'Invalid credentials.' } } })
    await store.login('manager@example.com', 'wrong')

    store.clearError()

    expect(store.error).toBeNull()
    expect(store.status).toBe('unknown')
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
