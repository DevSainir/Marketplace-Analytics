/**
 * Route table owned by the finreports module; exported via the Public API.
 *
 * `/finreports` is the P&L dashboard — the module's entry point.
 */
export const finreportsRoutes = [
  {
    path: '/finreports',
    name: 'finreports',
    component: () => import('@/modules/finreports/views/PnlView.vue'),
    meta: { title: 'P&L', requiresAuth: true, module: 'finreports' },
  },
  {
    path: '/finreports/cost-prices',
    name: 'finreports-cost-prices',
    component: () => import('@/modules/finreports/views/CostPricesView.vue'),
    meta: { title: 'Cost price', requiresAuth: true, module: 'finreports' },
  },
]
