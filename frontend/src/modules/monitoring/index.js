/**
 * PUBLIC API CONTRACT — monitoring module.
 *
 * The ONLY entry point other parts of the app may import from. Everything not
 * re-exported here (api.js, views, components) is module-private; deep imports
 * are fatal ESLint errors.
 */
export { monitoringRoutes } from '@/modules/monitoring/routes'
export { useMonitoringStore } from '@/modules/monitoring/store'
