/**
 * Workspace-context router guard.
 *
 * Every authenticated route needs the `X-Workspace-Id` header resolved BEFORE
 * its first API call (the backend rejects workspace-scoped requests without
 * it), so the guard awaits the one-time workspace bootstrap on any
 * `requiresAuth` navigation. Installed by main.js AFTER the auth guard —
 * guard order guarantees the session exists by the time this one runs.
 */
import { useAuthStore } from '@/modules/auth'
import { useWorkspaceStore } from '@/modules/profile/store'

export function installWorkspaceGuard(router) {
  router.beforeEach(async (to) => {
    if (!to.meta.requiresAuth) return true
    const auth = useAuthStore()
    if (!auth.isAuthenticated) return true // the auth guard already redirected

    try {
      await useWorkspaceStore().ensureLoaded()
    } catch {
      // A failed bootstrap (network hiccup, expired session mid-flight) must
      // not dead-end navigation: the view's own requests surface the error,
      // and the next navigation retries the bootstrap.
    }
    return true
  })
}
