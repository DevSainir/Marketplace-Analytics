/** Route table owned by the heatmap module; exported via the Public API. */

const view = () => import('@/modules/heatmap/views/HeatmapView.vue')

export const heatmapRoutes = [
  {
    // Open to every subscribed organisation since 2026-09-30. The monitoring
    // grant is the page; the settlement's money in it also needs P&L, which
    // the metric picker and the API check per metric.
    path: '/heatmap',
    name: 'heatmap',
    component: view,
    meta: { title: 'Тепловая карта', requiresAuth: true, modules: ['monitoring'] },
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
      modules: ['monitoring'],
    },
  },
]
