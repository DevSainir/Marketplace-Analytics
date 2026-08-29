/**
 * Auth module API layer — thin async wrappers over `/api/v1/auth/*`.
 *
 * The refresh token never appears here: the backend manages it as an HttpOnly
 * cookie, which the shared Axios client sends automatically
 * (`withCredentials: true`).
 */
import apiClient, { AUTH_TIMEOUT_MS } from '@/core/api/axios'

/**
 * POST /v1/auth/register — create a new account.
 *
 * Signup is open: the account it creates belongs to no organisation and reaches
 * nothing until an activation code or an invitation grants it access.
 *
 * @param {{email: string, password: string}} credentials
 * @returns {Promise<import('@/core/api/types').UserRead>}
 */
export async function registerUser({ email, password }) {
  const { data } = await apiClient.post('/v1/auth/register', {
    email,
    password,
  })
  return data
}

/**
 * POST /v1/auth/login — authenticate; sets the refresh cookie.
 *
 * @param {{email: string, password: string}} credentials
 * @returns {Promise<import('@/core/api/types').TokenPairResponse>}
 */
export async function loginUser({ email, password }) {
  const { data } = await apiClient.post('/v1/auth/login', { email, password })
  return data
}

/**
 * POST /v1/auth/refresh — rotate the refresh cookie into a new token pair.
 *
 * @returns {Promise<import('@/core/api/types').TokenPairResponse>}
 */
export async function refreshSession() {
  // The tight auth budget, not the 15 s data budget: the router guard awaits
  // this call on every app start, so its timeout bounds how long a user can
  // stare at a spinner when the backend hangs.
  const { data } = await apiClient.post('/v1/auth/refresh', undefined, {
    timeout: AUTH_TIMEOUT_MS,
  })
  return data
}

/** POST /v1/auth/logout — revoke the session and clear the cookie (204). */
export async function logoutUser() {
  await apiClient.post('/v1/auth/logout')
}
