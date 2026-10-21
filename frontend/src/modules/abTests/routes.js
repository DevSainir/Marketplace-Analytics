/** Route table owned by the A/B tests module; exported via the Public API. */
export const abTestsRoutes = [
  {
    path: '/ab-tests',
    name: 'ab-tests',
    component: () => import('@/modules/abTests/views/AbTestsView.vue'),
    meta: { title: 'A/Б-тесты', requiresAuth: true, module: 'ab_tests' },
  },
  {
    path: '/ab-tests/:testId',
    name: 'ab-test-detail',
    component: () => import('@/modules/abTests/views/AbTestDetailView.vue'),
    meta: { title: 'A/Б-тест', requiresAuth: true, module: 'ab_tests' },
  },
]
