/** Route table owned by the heatmap module; exported via the Public API. */

const view = () => import('@/modules/heatmap/views/HeatmapView.vue')

export const heatmapRoutes = [
  {
    // Open to every subscribed organisation since 2026-09-30. Both module
    // grants, like «Сводка» — the grid puts settlement money beside
    // monitoring's orders; the API asks for the same two.
    path: '/heatmap',
    name: 'heatmap',
    component: view,
    meta: { title: 'Тепловая карта', requiresAuth: true, modules: ['monitoring', 'finreports'] },
  },
  {
    // The same page with what is still being tried out — «Норма: ручной
    // ввод». Our own people only, here (`requiresInternal`) and on the norms
    // API (`require_internal`).
    path: '/labs/heatmap',
    name: 'labs-heatmap',
    component: view,
    props: { labs: true },
    meta: {
      title: 'Тепловая карта · Lab',
      requiresAuth: true,
      requiresInternal: true,
      modules: ['monitoring', 'finreports'],
    },
  },
]
