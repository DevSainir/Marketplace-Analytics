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

// Active workspace id, sent as the X-Workspace-Id header on every request.
// Persisted in localStorage so a reload keeps the user's workspace; the
// backend re-validates it on each request (an authenticated caller + an
// existing workspace), so a stale stored id degrades to a 404 the workspace
// store recovers from by re-selecting the first available workspace.
const WORKSPACE_STORAGE_KEY = 'workspace:id'

let workspaceId = localStorage.getItem(WORKSPACE_STORAGE_KEY)

export function getWorkspaceId() {
  return workspaceId
}

export function setWorkspaceId(id) {
  workspaceId = id
  if (id) {
    localStorage.setItem(WORKSPACE_STORAGE_KEY, id)
  } else {
    localStorage.removeItem(WORKSPACE_STORAGE_KEY)
  }
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

// summary fans out over a settlement window and legitimately takes seconds.
const DATA_TIMEOUT_MS = 15_000

/**
 * Budget for the auth surface — /refresh above all.
 *
 * Deliberately far tighter than `DATA_TIMEOUT_MS`, because this call is not a
 * report: it is a same-origin token rotation that a healthy backend answers in
 * ~3 ms (measured). Three seconds is a thousandfold margin, enough to absorb a
 * cold connection pool or a loaded box, and nothing more.
 *
 * Why it matters: the router guard awaits the session bootstrap, so this
 * timeout — multiplied by the store's retry ladder — IS the time a user spends
 * looking at a spinner when the backend hangs. On the shared 15 s budget that
 * worst case was ~50 s.
 */
export const AUTH_TIMEOUT_MS = 3_000

/**
 * Budget for a settlement window — the P&L and «Сводка» reads.
 *
 * These are the only calls whose cost scales with how much history the кабинет
 * has, and «Вся история» on the largest one is a genuine ~20 s of arithmetic
 * the first time it is asked for: the settlement rollup it is served from is
 * built on demand and verified against the detail on every read. On the shared
 * 15 s budget that came back as «Нет связи с сервером» — the one error message
 * that is certainly wrong, because the server was working the whole time.
 *
 * Harvests keep the rollup warm, so the common path is seconds; this is the
 * ceiling for the cold one, not the expected wait.
 */
export const WINDOW_TIMEOUT_MS = 60_000

const apiClient = axios.create({
  baseURL,
  withCredentials: true,
  // A hung backend must surface as an error, never an eternal pending promise:
  // the router guard awaits the session bootstrap, so one unbounded request
  // here freezes every navigation (blank page behind the header). The auth
  // store treats a timeout like any transient failure — bounded retries, then
  // guest → /login.
  timeout: DATA_TIMEOUT_MS,
  headers: { 'Content-Type': 'application/json' },
})

apiClient.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  if (workspaceId) {
    config.headers['X-Workspace-Id'] = workspaceId
  }
  // A FormData body must carry `multipart/form-data; boundary=…`, and only the
  // browser can name that boundary. The JSON default above is set on the
  // instance, so it outranks the one Axios would infer per request and the
  // upload goes out labelled `application/json` with a multipart body inside —
  // which the server cannot parse, and rejects as a malformed request rather
  // than a bad image. Deleting the header lets Axios fill it in.
  if (typeof FormData !== 'undefined' && config.data instanceof FormData) {
    delete config.headers['Content-Type']
  }
  return config
})

let refreshPromise = null

function refreshAccessToken() {
  // Deduplicate concurrent 401s into a single /refresh round-trip.
  refreshPromise ??= apiClient
    .post('/v1/auth/refresh', undefined, { timeout: AUTH_TIMEOUT_MS })
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
  // `error.message` is only safe when the throw is OURS. Axios writes its own
  // English — 'Network Error', 'timeout of 5000ms exceeded' — and this string
  // is shown to the user unaltered, so for an Axios failure it is replaced.
  // Errors the app raises itself already carry Russian written for the reader
  // (the monitoring store's poll-ceiling message, for one) and must survive.
  if (error.isAxiosError) {
    // Worth telling apart: one of these is worth retrying, the other is not.
    if (!error.response) return 'Нет связи с сервером. Проверьте подключение и повторите попытку.'
    return 'Непредвиденная ошибка. Повторите попытку позже.'
  }
  return error.message ?? 'Непредвиденная ошибка'
}

/**
 * The backend's machine-readable error code, when the envelope carries one.
 *
 * Views branch on this rather than on message text: the message is Russian
 * prose written for a person and is expected to be reworded, while the code is
 * the contract. `email_not_confirmed` is the one this exists for — it is the
 * difference between "your password is wrong" and "finish signing up".
 */
export function extractErrorCode(error) {
  return error.response?.data?.error?.code ?? null
}

export default apiClient
