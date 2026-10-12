/** Route table owned by the heatmap module; exported via the Public API. */
export const heatmapRoutes = [
  {
    // Open to every subscribed organisation since 2026-09-30, with hand-set
    // norms since 2026-10-01. Its own grant since 2026-10-12, and it opens
    // every metric, the settlement's money included (`require_heatmap`).
    path: '/heatmap',
    name: 'heatmap',
    component: () => import('@/modules/heatmap/views/HeatmapView.vue'),
    meta: { title: 'Тепловая карта', requiresAuth: true, module: 'heatmap' },
  },
  // Where it was tried out — kept so a saved link still lands.
  { path: '/labs/heatmap', redirect: '/heatmap' },
]
