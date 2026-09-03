/** Route table owned by the monitoring module; exported via the Public API. */
export const monitoringRoutes = [
  {
    // A PAGE of this module, not a module of its own: it reads the same SKUs,
    // the same window and the same chart machinery as the SKU view, and a
    // separate module would have had to import all three across a boundary
    // that exists to forbid exactly that.
    path: '/charts',
    name: 'charts',
    component: () => import('@/modules/monitoring/views/ChartsView.vue'),
    meta: { title: 'Графики', requiresAuth: true, module: 'monitoring' },
  },
  {
    path: '/monitoring',
    name: 'monitoring',
    component: () => import('@/modules/monitoring/views/MonitoringView.vue'),
    meta: { title: 'Мониторинг SKU', requiresAuth: true, module: 'monitoring' },
  },
]
