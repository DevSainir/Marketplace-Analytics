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
    // Статический датапак, ни одного вызова нашего API — но цифры в нём
    // настоящие, поэтому страница закрыта теми же двумя условиями, что и
    // соседняя: свой сеанс и свой человек.
    path: '/labs/finmodel',
    name: 'labs-finmodel',
    component: () => import('@/modules/labs/views/LabFinmodelView.vue'),
    meta: { title: 'Финмодель · Lab', requiresAuth: true, requiresInternal: true },
  },
]
