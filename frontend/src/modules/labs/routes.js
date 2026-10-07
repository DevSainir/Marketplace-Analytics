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
    // A one-for-one copy of /advertising on the same live API, to try a new
    // design against the page it would replace. Internal and the monitoring
    // grant, like the page and the API behind it.
    path: '/labs/advertising',
    name: 'labs-advertising',
    component: () => import('@/modules/labs/advertising/views/LabAdvertisingView.vue'),
    meta: {
      title: 'Реклама · Lab',
      requiresAuth: true,
      requiresInternal: true,
      modules: ['monitoring'],
    },
  },
  {
    // Блок «Реклама» вырос из лабы в модуль `advertising` на живых данных;
    // старая ссылка ведёт туда же.
    path: '/labs/advertisement-source',
    redirect: '/advertising',
  },
]
