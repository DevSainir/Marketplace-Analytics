import { createPinia, setActivePinia } from 'pinia'

import {
  confirmEmail,
  confirmPasswordReset,
  loginUser,
  logoutUser,
  refreshSession,
  registerUser,
  requestPasswordReset,
  resendConfirmation,
} from '@/modules/auth/api'
import { useAuthStore } from '@/modules/auth/store'

vi.mock('@/modules/auth/api', () => ({
  loginUser: vi.fn(),
  logoutUser: vi.fn(),
  refreshSession: vi.fn(),
  registerUser: vi.fn(),
  confirmEmail: vi.fn(),
  resendConfirmation: vi.fn(),
  requestPasswordReset: vi.fn(),
  confirmPasswordReset: vi.fn(),
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
  it('creates the account but does NOT sign it in', async () => {
    // Reversed on purpose. Registration used to log straight in, which meant an
    // abandoned signup left a usable session behind and the confirmation screen
    // was skippable by closing it. The account now exists and cannot be used
    // until the mailed code comes back — so leaving the page leaves nothing.
    registerUser.mockResolvedValue({ id: 'u1', email: 'new@example.com' })

    const ok = await store.register('new@example.com', 'secret-password')

    expect(ok).toBe(true)
    expect(loginUser).not.toHaveBeenCalled()
    expect(store.isAuthenticated).toBe(false)
    expect(store.needsConfirmation).toBe(true)
  })

  it('flags an unconfirmed account on login rather than reporting a bad password', async () => {
    loginUser.mockRejectedValue({
      response: {
        status: 403,
        data: { error: { code: 'email_not_confirmed', message: 'Аккаунт не активирован.' } },
      },
    })

    const ok = await store.login('half@example.com', 'secret-password')

    expect(ok).toBe(false)
    expect(store.needsConfirmation).toBe(true)
    expect(store.isAuthenticated).toBe(false)
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

describe('account recovery', () => {
  it('reports an accepted request without claiming the address exists', async () => {
    requestPasswordReset.mockResolvedValue({})

    await expect(store.askForPasswordReset('nobody@example.com')).resolves.toBe(true)
    expect(requestPasswordReset).toHaveBeenCalledWith({ email: 'nobody@example.com' })
    expect(store.error).toBeNull()
  })

  it('surfaces a refused code as an error rather than a silent false', async () => {
    confirmEmail.mockRejectedValue({ response: { data: { detail: 'Неверный код.' } } })

    await expect(store.confirmAddress('a@b.ru', '000000')).resolves.toBe(false)
    expect(store.error).toBe('Неверный код.')
  })

  it('drops the local session once a reset succeeds', async () => {
    // The backend has just ended EVERY session for the account, this browser's
    // included. Leaving the store believing it is signed in means the next
    // request is a 401 the user did not ask for.
    confirmPasswordReset.mockResolvedValue({})
    loginUser.mockResolvedValue(TOKENS)
    await store.login('a@b.ru', 'secret-enough')
    expect(store.isAuthenticated).toBe(true)

    await expect(store.resetPassword('a@b.ru', '123456', 'a-new-password')).resolves.toBe(true)

    expect(confirmPasswordReset).toHaveBeenCalledWith({
      email: 'a@b.ru',
      code: '123456',
      newPassword: 'a-new-password',
    })
    expect(store.isAuthenticated).toBe(false)
    expect(store.userEmail).toBeNull()
    expect(localStorage.getItem('auth:email')).toBeNull()
  })

  it('keeps the session when the reset is refused', async () => {
    confirmPasswordReset.mockRejectedValue({ response: { data: { detail: 'Просрочен.' } } })
    loginUser.mockResolvedValue(TOKENS)
    await store.login('a@b.ru', 'secret-enough')

    await expect(store.resetPassword('a@b.ru', '000000', 'a-new-password')).resolves.toBe(false)

    expect(store.isAuthenticated).toBe(true)
    expect(store.error).toBe('Просрочен.')
  })

  it('does not report a timeout as a failure when a code was consumed', async () => {
    // The server consumes the code, changes the password and ends every session
    // before it answers, so "no response" is not "nothing happened". Saying it
    // failed sends the user back to a form whose code is already spent.
    confirmPasswordReset.mockRejectedValue(
      Object.assign(new Error('timeout of 15000ms exceeded'), {
        response: undefined,
      }),
    )

    await expect(store.resetPassword('a@b.ru', '123456', 'a-new-password')).resolves.toBe(false)

    expect(store.error).toContain('Пароль мог быть изменён')
    expect(store.error).not.toContain('timeout')
  })

  it('still reports a refusal from its own message', async () => {
    confirmPasswordReset.mockRejectedValue({ response: { data: { detail: 'Просрочен.' } } })

    await store.resetPassword('a@b.ru', '000000', 'a-new-password')

    expect(store.error).toBe('Просрочен.')
  })

  it('clears loading on both paths', async () => {
    resendConfirmation.mockRejectedValue(new Error('network'))

    await store.askForConfirmationCode('a@b.ru')

    expect(store.loading).toBe(false)
  })
})
