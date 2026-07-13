/**
 * Base Axios client for the FastAPI backend.
 *
 * - `baseURL` comes strictly from the environment (never hardcoded).
 * - `withCredentials: true` so the HttpOnly refresh cookie set by
 *   `/v1/auth/login` / `/v1/auth/refresh` travels with every request.
 * - Requests carry the in-memory access token as a Bearer header.
 * - A global 401 interceptor transparently rotates the refresh token once and
 *   retries; if rotation fails the session is dead and the registered
 *   unauthorized handler (installed by the auth module) takes over.
 *
 * This file must stay module-agnostic: it knows nothing about routes or
 * stores. The auth module plugs itself in via `setUnauthorizedHandler`.
 */
import axios from 'axios'

let accessToken = null

export function setAccessToken(token) {
  accessToken = token
}

export function clearAccessToken() {
  accessToken = null
}

// Called when the session is unrecoverable (401 + failed refresh). The auth
// module registers a router-aware handler; the fallback is a hard redirect.
let unauthorizedHandler = () => {
  if (window.location.pathname !== '/login') {
    window.location.assign('/login')
  }
}

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler
}

// `baseURL` defaults to the relative `/api`, which works identically in both
// environments: the Vite dev server proxies /api/* to the local backend, and
// in production nginx reverse-proxies it to the api container (same origin,
// no CORS). VITE_API_URL remains available as an escape hatch for pointing a
// build at a remote backend.
const baseURL = import.meta.env.VITE_API_URL || '/api'

const apiClient = axios.create({
  baseURL,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

apiClient.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

let refreshPromise = null

function refreshAccessToken() {
  // Deduplicate concurrent 401s into a single /refresh round-trip.
  refreshPromise ??= apiClient
    .post('/v1/auth/refresh')
    .then(({ data }) => {
      setAccessToken(data.access_token)
      return data.access_token
    })
    .finally(() => {
      refreshPromise = null
    })
  return refreshPromise
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { config, response } = error
    const isAuthEndpoint = config?.url?.startsWith('/v1/auth/')

    if (response?.status === 401 && config && !config._retried && !isAuthEndpoint) {
      config._retried = true
      try {
        await refreshAccessToken()
        return apiClient(config)
      } catch {
        clearAccessToken()
        unauthorizedHandler()
      }
    }

    return Promise.reject(error)
  },
)

/**
 * Extract a human message from a backend error response.
 *
 * Domain errors use the `{error: {code, message}}` envelope; FastAPI's own
 * auth/validation errors use `{detail: string | object[]}`.
 */
export function extractErrorMessage(error) {
  const data = error.response?.data
  if (data?.error?.message) return data.error.message
  if (typeof data?.detail === 'string') return data.detail
  if (Array.isArray(data?.detail) && data.detail[0]?.msg) return data.detail[0].msg
  return error.message ?? 'Непредвиденная ошибка'
}

export default apiClient
