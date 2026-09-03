/**
 * Workspace-context and internal-features router guards.
 *
 * Every authenticated route needs the `X-Workspace-Id` header resolved BEFORE
 * its first API call (the backend rejects workspace-scoped requests without
 * it), so the guard awaits the one-time workspace bootstrap on any
 * `requiresAuth` navigation. Installed by main.js AFTER the auth guard —
 * guard order guarantees the session exists by the time this one runs.
 */
import { useAuthStore } from '@/modules/auth'
import { useMembersStore } from '@/modules/profile/membersStore'
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

/**
 * Keep customers out of the surfaces built for us.
 *
 * our own legal case against WB. The API has always refused them to anyone
 * else (`require_internal`), but the SPA did not: the routes carried only
 * `requiresAuth`, so any signed-in customer could open the page and watch its
 * requests come back 403. A feature a customer is told does not exist should
 * not render a screen for them.
 *
 * Answers with a rewrite to the not-found view rather than a redirect, for the
 * same reason the backend phrases its refusal as "Раздел недоступен." — to a
 * customer, this section does not exist, and a bounce to the dashboard would
 * confirm that something is there.
 */
export function installInternalGuard(router) {
  router.beforeEach(async (to) => {
    if (!to.meta.requiresInternal) return true
    const auth = useAuthStore()
    if (!auth.isAuthenticated) return true // the auth guard already redirected

    const members = useMembersStore()
    try {
      await members.ensureLoaded()
    } catch {
      // Fail CLOSED. Everywhere else a failed bootstrap lets navigation
      // continue and the view reports its own error; here an unanswered
      // question about who you are must not resolve to "one of us".
      return {
        name: 'not-found',
        params: { pathMatch: to.path.slice(1).split('/') },
        replace: true,
      }
    }
    if (!members.internalFeatures) {
      return {
        name: 'not-found',
        params: { pathMatch: to.path.slice(1).split('/') },
        replace: true,
      }
    }
    return true
  })
}
