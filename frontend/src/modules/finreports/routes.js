/**
 * Route table owned by the finreports module; exported via the Public API.
 *
 * the claim is easiest to act on right after seeing how large that line is.
 */
export const finreportsRoutes = [
  {
    path: '/finreports',
    name: 'finreports',
    component: () => import('@/modules/finreports/views/PnlView.vue'),
    meta: { title: 'Прибыли и убытки', requiresAuth: true, module: 'finreports' },
  },
  {
  },
  {
    path: '/finreports/cost-prices',
    name: 'finreports-cost-prices',
    component: () => import('@/modules/finreports/views/CostPricesView.vue'),
    meta: { title: 'Себестоимость', requiresAuth: true, module: 'finreports' },
  },
]
