/**
 * Router integration for the auth module.
 *
 * Installed from the app entrypoint (`main.js`) so `src/core/router` stays
 * module-agnostic. Responsibilities:
 *   - resolve the session once before the first navigation (silent refresh);
 *   - gate `meta.requiresAuth` routes behind /login (preserving the target);
 *   - bounce authenticated users away from `meta.guestOnly` routes;
 *   - register the core Axios unauthorized handler so a dead session mid-use
 *     lands on /login via the router instead of a hard page reload.
 */
import { setUnauthorizedHandler } from '@/core/api/axios'
import { useAuthStore } from '@/modules/auth/store'

export const AFTER_LOGIN_ROUTE = '/monitoring'

/** Sanitize a ?redirect= value: only same-app paths are allowed. */
export function safeRedirect(value, fallback = AFTER_LOGIN_ROUTE) {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')
    ? value
    : fallback
}

export function installAuthGuard(router) {
  router.beforeEach(async (to) => {
    const auth = useAuthStore()
    await auth.bootstrap()

    if (to.meta.requiresAuth && !auth.isAuthenticated) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
    if (to.meta.guestOnly && auth.isAuthenticated) {
      return safeRedirect(to.query.redirect)
    }
    return true
  })

  setUnauthorizedHandler(() => {
    const auth = useAuthStore()
    auth.markGuest()
    const current = router.currentRoute.value
    if (current.name !== 'login') {
      router.push({ name: 'login', query: { redirect: current.fullPath } })
    }
  })
}
