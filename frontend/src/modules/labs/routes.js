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
  {
    // This one DOES call the API — it is the profile page relaid out, running
    // on the real stores so the layout can be judged against real data (a
    // fixture team of three would prove nothing about a team of one). Same
    // internal-only gate as the rest of the labs.
    path: '/labs/profile',
    name: 'labs-profile',
    component: () => import('@/modules/labs/views/LabProfileView.vue'),
    meta: { title: 'Профиль · Lab', requiresAuth: true, requiresInternal: true },
  },
]
