/**
 * PUBLIC API CONTRACT — summary module.
 *
 * "Summary": the whole workspace in one window — what it earned, what it kept, and
 * which articles produced both. It owns no data of its own; the backend derives
 * every figure from the same reconciled settlement cut the P&L's per-SKU table reads, so
 * the two screens cannot disagree about one seller's revenue.
 *
 * The ONLY entry point other parts of the app may import from.
 */
export { summaryRoutes } from '@/modules/summary/routes'
