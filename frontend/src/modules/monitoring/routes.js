/** Route table owned by the monitoring module; exported via the Public API. */
export const monitoringRoutes = [
  {
    path: '/monitoring',
    name: 'monitoring',
    component: () => import('@/modules/monitoring/views/MonitoringView.vue'),
    meta: { title: 'SKU monitoring', requiresAuth: true, module: 'monitoring' },
  },
]
