/** Route table owned by the finreports module; exported via the Public API. */
export const finreportsRoutes = [
  {
    path: '/finreports',
    name: 'finreports',
    component: () => import('@/modules/finreports/views/FinReportsView.vue'),
  },
]
