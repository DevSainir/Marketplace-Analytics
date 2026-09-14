/**
 * PUBLIC API CONTRACT — labs module.
 *
 * A design sandbox: one route that reproduces the monitoring page's structure
 * under a SECOND, self-contained design system. It exists to be compared
 * against /monitoring, so it deliberately shares nothing with the monitoring
 * module — not its store, not its components, not its tokens. Everything it
 * renders comes from `fixtures.js`.
 *
 * `/labs/profile` lived here too, on the real stores rather than on fixtures,
 * until the layout it was trying out became the actual profile page. A sandbox
 * that has shipped is not a sandbox.
 *
 * The ONLY entry point other parts of the app may import from.
 */
export { labsRoutes } from '@/modules/labs/routes'
