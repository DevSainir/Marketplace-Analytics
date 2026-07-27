/**
 * Auth Pinia store (Composition-API setup style).
 *
 * The access token itself lives in the core Axios client (module-scoped, never
 * rendered); this store owns the session lifecycle: login, registration,
 * bootstrap (silent refresh on app start via the HttpOnly cookie) and logout.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { clearAccessToken, extractErrorMessage, setAccessToken } from '@/core/api/axios'
import { loginUser, logoutUser, refreshSession, registerUser } from '@/modules/auth/api'

// Cosmetic only (header display); the session itself is cookie-based.
const EMAIL_STORAGE_KEY = 'auth:email'

export const useAuthStore = defineStore('auth', () => {
  // --- state -------------------------------------------------------------
  const loading = ref(false)
  const error = ref(null)
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
  //   3s + 0.4s + 3s + 1s + 3s ≈ 10s   (was 15s + 1s + 15s + 3s + 15s ≈ 50s)
  //
  // Giving up sooner is cheap here: the HttpOnly refresh cookie is untouched,
  // so a user bounced to /login by a backend blip is logged straight back in by
  // a reload. Fifty seconds of spinner was not cheap.
  const BOOTSTRAP_RETRY_DELAYS_MS = [400, 1_000]
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
    try {
      const tokens = await loginUser({ email, password })
      applySession(tokens)
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

  /** Register a new account (invite-only), then log straight into it. */
  async function register(email, password, inviteCode) {
    loading.value = true
    error.value = null
    try {
      await registerUser({ email, password, inviteCode })
    } catch (err) {
      error.value = extractErrorMessage(err)
      loading.value = false
      return false
    }
    return login(email, password)
  }

  /** Dismiss the last auth error (e.g. when the user switches login/register). */
  function clearError() {
    error.value = null
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
  }
})
