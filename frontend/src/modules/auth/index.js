/**
 * PUBLIC API CONTRACT — auth module.
 *
 * The ONLY entry point other parts of the app may import from. Everything not
 * re-exported here (api.js, views, guard internals) is module-private; deep
 * imports are fatal ESLint errors.
 */
export { authRoutes } from '@/modules/auth/routes'
export { useAuthStore } from '@/modules/auth/store'
export { installAuthGuard, AFTER_LOGIN_ROUTE } from '@/modules/auth/guard'
