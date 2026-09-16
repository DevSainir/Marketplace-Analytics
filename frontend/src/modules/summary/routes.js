/** Route table owned by the summary module; exported via the Public API. */
export const summaryRoutes = [
  {
    // Lives under /labs while the method is still ours to explain: the margin
    // is withheld until every SKU is costed, and WB's weekly advertising
    // invoice is restated onto the days the ads actually ran. Both are right
    // and neither is what WB's own cabinet shows, so the page stays internal
    // until that difference is something a seller has been told about.
    path: '/labs/summary',
    name: 'labs-summary',
    component: () => import('@/modules/summary/views/SummaryView.vue'),
    meta: { title: 'Сводка · Lab', requiresAuth: true, requiresInternal: true },
  },
]
