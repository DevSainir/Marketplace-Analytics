/** Route table owned by the heatmap module; exported via the Public API. */
export const heatmapRoutes = [
  {
    // Open to every subscribed organisation since 2026-09-30. Both module
    // grants, like «Сводка» — the grid puts settlement money beside
    // monitoring's orders; the API asks for the same two.
    path: '/heatmap',
    name: 'heatmap',
    component: () => import('@/modules/heatmap/views/HeatmapView.vue'),
    meta: {
      title: 'Тепловая карта',
      requiresAuth: true,
      modules: ['monitoring', 'finreports'],
    },
  },
  // Where it lived while it was a lab — kept so a saved link still lands.
  { path: '/labs/heatmap', redirect: '/heatmap' },
]
