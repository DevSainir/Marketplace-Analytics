/**
 * PUBLIC API CONTRACT — labs module.
 *
 * A design sandbox. Two routes, and they are sandboxes in different senses:
 *
 *  - `/labs/monitoring` reproduces the monitoring page's structure under a
 *    SECOND design system, sharing nothing with the monitoring module — not its
 *    store, not its components, not its tokens. Everything it renders comes
 *    from `fixtures.js`.
 *  - `/labs/profile` re-lays out the profile page on the REAL stores and the
 *    real endpoints. Only the layout is new, so what is being compared is the
 *    layout; fixtures would have hidden exactly the cases the redesign is
 *    about (a team of one, a workspace with no tokens, a lapsed term).
 *
 * The ONLY entry point other parts of the app may import from.
 */
export { labsRoutes } from '@/modules/labs/routes'
