/**
 * Auth Pinia store (Composition-API setup style).
 *
 * The access token itself lives in the core Axios client (module-scoped, never
 * rendered); this store owns the session lifecycle: login, registration,
 * bootstrap (silent refresh on app start via the HttpOnly cookie) and logout.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  clearAccessToken,
  extractErrorCode,
  extractErrorMessage,
  setAccessToken,
} from '@/core/api/axios'
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

// Cosmetic only (header display); the session itself is cookie-based.
const EMAIL_STORAGE_KEY = 'auth:email'

export const useAuthStore = defineStore('auth', () => {
  // --- state -------------------------------------------------------------
  const loading = ref(false)
  const error = ref(null)
  /** The last register attempt failed because the address is already taken. */
  const emailTaken = ref(false)
  /**
   * The last login or register attempt hit an account that exists but has never
   * confirmed its address. The view sends the person to the code screen.
   */
  const needsConfirmation = ref(false)
  /** 'unknown' until bootstrap resolves, then 'authenticated' | 'guest'. */
  const status = ref('unknown')
  const userEmail = ref(localStorage.getItem(EMAIL_STORAGE_KEY))
  const accessExpiresAt = ref(null)

  let bootstrapPromise = null

  // --- getters -----------------------------------------------------------
  const isAuthenticated = computed(() => status.value === 'authenticated')

  // --- internal helpers ----------------------------------------------------
  // Proactive refresh: rotate the access token ~60s before it expires so
  // requests never race the 401 interceptor. One timer per session.
  const REFRESH_LEEWAY_MS = 60_000

  // Only an explicit rejection of the refresh cookie means the session is
  // over. Anything else (network blip, 429, 5xx, backend restarting during a
  // deploy) is TRANSIENT — treating it as "logged out" was bouncing users to
  // /login when a plain reload would have succeeded.
  const isSessionRejected = (err) => [401, 403].includes(err?.response?.status)

  // Bootstrap retry delays for transient refresh failures.
  //
  // These, times the auth request timeout, are the worst case a user waits
  // before the app decides "guest" and shows the login screen:
  //   ~3s + 0.4 + 3 + 1 + 3 + 4 + 3 + 8 + 3 ≈ 28s
  //
  // Extended from ~10s on 2026-08-17: a deploy recreates the api container, and
  // for those seconds /refresh answers nothing at all. Ten seconds was inside
  // that window, so every deploy threw logged-in users onto /login mid-session —
  // exactly the "it kicked me off" report. The trade is a longer worst-case
  // spinner for a user whose backend is genuinely down, which is the rarer and
  // less damaging case; the HttpOnly cookie survives either way, so nobody has
  // to type a password again.
  const BOOTSTRAP_RETRY_DELAYS_MS = [400, 1_000, 4_000, 8_000]
  // Proactive-refresh retry delay: the current token is still valid, so a
  // transient failure just tries again shortly instead of dropping the session.
  const PROACTIVE_RETRY_MS = 20_000

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

  let refreshTimer = null

  function clearRefreshTimer() {
    if (refreshTimer !== null) {
      clearTimeout(refreshTimer)
      refreshTimer = null
    }
  }

  function scheduleProactiveRefresh(expiresAt) {
    clearRefreshTimer()
    const expiryMs = Date.parse(expiresAt)
    if (!Number.isFinite(expiryMs)) return // unknown expiry: 401 interceptor covers us
    scheduleRefreshAttempt(Math.max(expiryMs - Date.now() - REFRESH_LEEWAY_MS, 1_000))
  }

  function scheduleRefreshAttempt(delay) {
    refreshTimer = setTimeout(async () => {
      refreshTimer = null
      try {
        applySession(await refreshSession())
      } catch (err) {
        if (isSessionRejected(err)) {
          markGuest() // dead refresh cookie: the session is over
        } else {
          // Transient: keep the session and retry; even past expiry the 401
          // interceptor still refreshes on demand.
          scheduleRefreshAttempt(PROACTIVE_RETRY_MS)
        }
      }
    }, delay)
  }

  function applySession(tokens) {
    setAccessToken(tokens.access_token)
    accessExpiresAt.value = tokens.expires_at
    status.value = 'authenticated'
    scheduleProactiveRefresh(tokens.expires_at)
  }

  /** Drop the local session (no server call) — e.g. after a failed refresh. */
  function markGuest() {
    clearRefreshTimer()
    clearAccessToken()
    accessExpiresAt.value = null
    status.value = 'guest'
  }

  // --- actions -------------------------------------------------------------
  /**
   * Resolve the session once per app load: try to rotate the refresh cookie
   * into an access token. Concurrent callers (router guard + views) share one
   * request; subsequent calls are no-ops.
   */
  function bootstrap() {
    if (status.value !== 'unknown') return Promise.resolve()
    bootstrapPromise ??= (async () => {
      for (let attempt = 0; ; attempt += 1) {
        try {
          applySession(await refreshSession())
          return
        } catch (err) {
          // A rejected cookie means guest; a transient failure gets a couple
          // of quick retries before giving up (the guard awaits this, so the
          // total stall is bounded to a few seconds).
          if (isSessionRejected(err) || attempt >= BOOTSTRAP_RETRY_DELAYS_MS.length) {
            markGuest()
            return
          }
          await sleep(BOOTSTRAP_RETRY_DELAYS_MS[attempt])
        }
      }
    })().finally(() => {
      bootstrapPromise = null
    })
    return bootstrapPromise
  }

  async function login(email, password) {
    loading.value = true
    error.value = null
    needsConfirmation.value = false
    try {
      const tokens = await loginUser({ email, password })
      applySession(tokens)
      userEmail.value = email
      localStorage.setItem(EMAIL_STORAGE_KEY, email)
      return true
    } catch (err) {
      error.value = extractErrorMessage(err)
      // Credentials were right; the address was never proven. Not a failure to
      // report so much as a step to finish, so the view routes rather than
      // showing a red box.
      needsConfirmation.value = extractErrorCode(err) === 'email_not_confirmed'
      return false
    } finally {
      loading.value = false
    }
  }

  /** Register a new account, then log straight into it. */
  async function register(email, password) {
    loading.value = true
    error.value = null
    emailTaken.value = false
    needsConfirmation.value = false
    try {
      await registerUser({ email, password })
    } catch (err) {
      error.value = extractErrorMessage(err)
      // An unfinished signup coming back round. Same destination as the login
      // case: the code screen, not an error.
      needsConfirmation.value = extractErrorCode(err) === 'email_not_confirmed'
      // A 409 is the commonest way this form fails, and it is nearly always
      // the SAME person coming back: registration creates the account before
      // the address is confirmed, so anyone who abandoned the confirmation
      // step meets "already exists" on their second try. Flagged separately
      // from the message so the form can offer the way out instead of leaving
      // them to work out that the account they are being refused is theirs.
      emailTaken.value = err?.response?.status === 409
      loading.value = false
      return false
    }
    // NOT `login()`. Registration issues no session by design — the account
    // exists but cannot be used until the mailed code comes back, so signing
    // them in here would be inventing the access the backend just withheld.
    loading.value = false
    userEmail.value = email
    needsConfirmation.value = true
    return true
  }

  /** Dismiss the last auth error (e.g. when the user switches login/register). */
  function clearError() {
    error.value = null
    emailTaken.value = false
    needsConfirmation.value = false
  }

  // --- account recovery (register P1.6) ----------------------------------
  //
  // One shape for all four: flip `loading`, clear `error`, return a boolean the
  // view can branch on. They are separate from `login`/`register` because none
  // of them establishes a session — two of them deliberately END one.
  //
  // The two "request" calls answer 202 for an address that does not exist, on
  // purpose: a recovery form that says "no such user" is an account-existence
  // oracle reachable without even a password guess. `true` here therefore means
  // "the request was accepted", never "that address is registered", and the
  // views must not phrase it as the latter.

  /**
   * Run one recovery call, reporting whether it was accepted.
   *
   * `noResponseMessage` covers the case an error envelope cannot: no response
   * at all — a timeout, a dropped connection. For the two calls that CONSUME a
   * mailed code that is not the same as failing. The server consumes the code,
   * changes the state and only then answers, so a timeout leaves the user with
   * a spent code and, quite possibly, the change already made. Reporting the
   * axios message there ("timeout of 15000ms exceeded") is both untranslated
   * and wrong about what happened.
   */
  async function runRecovery(call, noResponseMessage = null) {
    loading.value = true
    error.value = null
    try {
      await call()
      return true
    } catch (err) {
      error.value =
        noResponseMessage && !err.response ? noResponseMessage : extractErrorMessage(err)
      return false
    } finally {
      loading.value = false
    }
  }

  /** Ask for a fresh confirmation code. Accepted for any address. */
  function askForConfirmationCode(email) {
    return runRecovery(() => resendConfirmation({ email }))
  }

  /**
   * Redeem a confirmation code, and take the session it answers with.
   *
   * `/confirm-email` signs the caller in: registration hands out no tokens, so
   * this is the moment the account becomes usable, and by now the person has
   * proved both halves of the credential — the mailbox, and (because the
   * password is bound to the code) that they chose the password. Sending them
   * back to the login form to retype it would prove nothing.
   *
   * False means the code was wrong, expired or already used.
   */
  async function confirmAddress(email, code) {
    loading.value = true
    error.value = null
    try {
      applySession(await confirmEmail({ email, code }))
      userEmail.value = email
      localStorage.setItem(EMAIL_STORAGE_KEY, email)
      return true
    } catch (err) {
      error.value = extractErrorMessage(err)
      return false
    } finally {
      loading.value = false
    }
  }

  /** Ask for a password-reset code. Accepted for any address. */
  function askForPasswordReset(email) {
    return runRecovery(() => requestPasswordReset({ email }))
  }

  /**
   * Set a new password against a mailed code.
   *
   * On success the backend has ended EVERY session for the account — this
   * browser's included — so the local session is dropped here rather than left
   * to expire against a server that has already stopped honouring it.
   */
  async function resetPassword(email, code, newPassword) {
    const ok = await runRecovery(
      () => confirmPasswordReset({ email, code, newPassword }),
      'Ответ от сервера не получен. Пароль мог быть изменён — попробуйте войти с новым паролем, и запросите код заново, если не получится.',
    )
    if (ok) {
      markGuest()
      userEmail.value = null
      localStorage.removeItem(EMAIL_STORAGE_KEY)
    }
    return ok
  }

  async function logout() {
    try {
      await logoutUser()
    } catch {
      // Logout is idempotent server-side; locally we always drop the session.
    }
    markGuest()
    userEmail.value = null
    localStorage.removeItem(EMAIL_STORAGE_KEY)
  }

  return {
    loading,
    error,
    emailTaken,
    needsConfirmation,
    status,
    userEmail,
    accessExpiresAt,
    isAuthenticated,
    bootstrap,
    login,
    register,
    logout,
    markGuest,
    clearError,
    askForConfirmationCode,
    confirmAddress,
    askForPasswordReset,
    resetPassword,
  }
})
