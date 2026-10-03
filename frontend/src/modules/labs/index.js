/**
 * PUBLIC API CONTRACT — labs module.
 *
 * Two routes that have one thing in common: neither is part of the product yet,
 * and both are allowed a design system of their own.
 *
 * `/labs/finmodel` is the finance one-pager from `docs/finmodelka/` — real
 * numbers off a static datapack, its own tokens, its logic left on bare DOM
 * because those figures are checked against that folder's control values and
 * a rewrite onto reactivity would have moved them.
 *
 * `/labs/advertisement-source` is that page's «Реклама» tab re-laid in the
 * app's own design system, off the same datapack — the step between the
 * one-pager and the product. Everything it needs lives in its folder, so it
 * can move into a product module piece by piece.
 *
 * `/labs/monitoring` is a design sandbox: one route that reproduces the monitoring page's structure
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
