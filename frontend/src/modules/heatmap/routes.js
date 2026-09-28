/** Route table owned by the heatmap module; exported via the Public API. */
export const heatmapRoutes = [
  {
    // Under /labs while it is tried out: our own people only, on the SPA side
    // (`requiresInternal`) and again on the API (`require_internal`). Both
    // module grants, like «Сводка» — the grid puts settlement money beside
    // monitoring's orders.
    path: '/labs/heatmap',
    name: 'labs-heatmap',
    component: () => import('@/modules/heatmap/views/HeatmapView.vue'),
    meta: {
      title: 'Тепловая карта · Lab',
      requiresAuth: true,
      requiresInternal: true,
      modules: ['monitoring', 'finreports'],
    },
  },
]
