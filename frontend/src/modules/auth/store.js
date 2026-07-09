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
  function applySession(tokens) {
    setAccessToken(tokens.access_token)
    accessExpiresAt.value = tokens.expires_at
    status.value = 'authenticated'
  }

  /** Drop the local session (no server call) — e.g. after a failed refresh. */
  function markGuest() {
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
    bootstrapPromise ??= refreshSession()
      .then(applySession)
      .catch(markGuest)
      .finally(() => {
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

  /** Register a new account, then log straight into it. */
  async function register(email, password) {
    loading.value = true
    error.value = null
    try {
      await registerUser({ email, password })
    } catch (err) {
      error.value = extractErrorMessage(err)
      loading.value = false
      return false
    }
    return login(email, password)
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
  }
})
