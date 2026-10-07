/**
 * PUBLIC API CONTRACT — labs module.
 *
 * `/labs/advertising` is a one-for-one copy of the `advertising` module's page
 * (its own components and store, on the same live API) for trying a new design
 * against the page it would replace. Labs may not import the module's
 * internals, so it is a copy rather than a reuse, and it drifts from the live
 * page the moment either is changed — that is the point of it.
 *
 * `/labs/monitoring` is a fixture sandbox. The finance one-pager that
 * used to live at `/labs/finmodel` was removed on 2026-10-07: it was a static
 * reference with its own design system, not a page anyone works in. Its
 * «Реклама» tab had already become the `advertising` module, and
 * `/labs/advertisement-source` still redirects there.
 *
 * It is a design sandbox: one route that reproduces the monitoring page's structure
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
