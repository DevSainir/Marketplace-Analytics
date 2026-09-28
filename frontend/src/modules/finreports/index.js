/**
 * PUBLIC API CONTRACT — finreports module.
 *
 * The ONLY entry point other parts of the app may import from. Everything not
 * re-exported here (api.js, store.js, views, components) is module-private; deep
 * imports are fatal ESLint errors — same rule as the monitoring module.
 *
 * `useCurrencyStore` is here because the settlement currency is this module's
 * fact and every page that prints money needs it.
 */
export { useCurrencyStore } from '@/modules/finreports/currencyStore'
export { finreportsRoutes } from '@/modules/finreports/routes'
