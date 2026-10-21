/**
 * PUBLIC API CONTRACT — A/B tests module.
 *
 * The ONLY entry point other parts of the app may import from. Everything not
 * re-exported here (api.js, views, components) is module-private; deep imports
 * are fatal ESLint errors.
 */
export { abTestsRoutes } from '@/modules/abTests/routes'
export {
  MAX_VARIANTS,
  STATUS_LABELS,
  statusLabel,
  statusTone,
  useAbTestsStore,
} from '@/modules/abTests/store'
