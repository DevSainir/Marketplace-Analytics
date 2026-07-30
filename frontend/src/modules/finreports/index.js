/**
 * PUBLIC API CONTRACT — finreports module.
 *
 * The ONLY entry point other parts of the app may import from. Everything not
 * re-exported here (api.js, store.js, views, components) is module-private; deep
 * imports are fatal ESLint errors — same rule as the monitoring module.
 */
export { finreportsRoutes } from '@/modules/finreports/routes'
