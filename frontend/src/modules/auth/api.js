/**
 * Auth module API layer — thin async wrappers over `/api/v1/auth/*`.
 *
 * The refresh token never appears here: the backend manages it as an HttpOnly
 * cookie, which the shared Axios client sends automatically
 * (`withCredentials: true`).
 */
import apiClient from '@/core/api/axios'

/**
 * POST /v1/auth/register — create a new account (invite-only).
 *
 * @param {{email: string, password: string, inviteCode: string}} credentials
 * @returns {Promise<import('@/core/api/types').UserRead>}
 */
export async function registerUser({ email, password, inviteCode }) {
  const { data } = await apiClient.post('/v1/auth/register', {
    email,
    password,
    invite_code: inviteCode,
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
  const { data } = await apiClient.post('/v1/auth/refresh')
  return data
}

/** POST /v1/auth/logout — revoke the session and clear the cookie (204). */
export async function logoutUser() {
  await apiClient.post('/v1/auth/logout')
}
