/** Route table owned by the labs module; exported via the Public API. */
export const labsRoutes = [
  {
    // Deliberately not behind `requiresAuth`: the page renders fixtures, has no
    // API calls, and being able to open it without a session is the point of a
    // design sandbox.
    path: '/labs/monitoring',
    name: 'labs-monitoring',
    component: () => import('@/modules/labs/views/LabMonitoringView.vue'),
    meta: { title: 'Мониторинг · Lab', requiresAuth: true, requiresInternal: true },
  },
]
