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

/**
 * POST /v1/auth/confirm-email — prove control of an address with a mailed code.
 *
 * @param {{email: string, code: string}} payload
 * @returns {Promise<{detail?: string}>}
 */
export async function confirmEmail({ email, code }) {
  const { data } = await apiClient.post('/v1/auth/confirm-email', { email, code })
  return data
}

/**
 * POST /v1/auth/resend-confirmation — ask for a fresh confirmation code.
 *
 * Always resolves (202) whether or not the address exists — the backend refuses
 * to be an account-existence oracle, so the UI must not present this as a
 * lookup either.
 *
 * @param {{email: string}} payload
 * @returns {Promise<{detail?: string}>}
 */
export async function resendConfirmation({ email }) {
  const { data } = await apiClient.post('/v1/auth/resend-confirmation', { email })
  return data
}

/**
 * POST /v1/auth/password-reset/request — mail a reset code.
 *
 * Same uniformity rule as `resendConfirmation`: 202 for every address.
 *
 * @param {{email: string}} payload
 * @returns {Promise<{detail?: string}>}
 */
export async function requestPasswordReset({ email }) {
  const { data } = await apiClient.post('/v1/auth/password-reset/request', { email })
  return data
}

/**
 * POST /v1/auth/password-reset/confirm — set a new password against the code.
 *
 * Succeeding here ends every session the account had, including any this
 * browser holds, so the caller must send the user back to the login screen.
 *
 * @param {{email: string, code: string, newPassword: string}} payload
 * @returns {Promise<{detail?: string}>}
 */
export async function confirmPasswordReset({ email, code, newPassword }) {
  const { data } = await apiClient.post('/v1/auth/password-reset/confirm', {
    email,
    code,
    new_password: newPassword,
  })
  return data
}
