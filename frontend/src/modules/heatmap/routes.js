/** Route table owned by the heatmap module; exported via the Public API. */
export const heatmapRoutes = [
  {
    // Open to every subscribed organisation since 2026-09-30, with hand-set
    // norms since 2026-10-01. The monitoring grant is the page; the
    // settlement's money in it also needs P&L, which the metric picker and the
    // API check per metric.
    path: '/heatmap',
    name: 'heatmap',
    component: () => import('@/modules/heatmap/views/HeatmapView.vue'),
    meta: { title: 'Тепловая карта', requiresAuth: true, modules: ['monitoring'] },
  },
  // Where it was tried out — kept so a saved link still lands.
  { path: '/labs/heatmap', redirect: '/heatmap' },
]
