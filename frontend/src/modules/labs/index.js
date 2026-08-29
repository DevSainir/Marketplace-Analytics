/**
 * PUBLIC API CONTRACT — labs module.
 *
 * A design sandbox: one route that reproduces the monitoring page's structure
 * under a SECOND, self-contained design system (`theme.css`). It exists to be
 * compared against /monitoring, so it deliberately shares nothing with the
 * monitoring module — not its store, not its components, not its tokens.
 * Everything it renders comes from `fixtures.js`.
 *
 * The ONLY entry point other parts of the app may import from.
 */
export { labsRoutes } from '@/modules/labs/routes'
