/** Route table owned by the advertising module; exported via the Public API. */
export const advertisingRoutes = [
  {
    // Internal while it is being built, like the API behind it
    // (`require_internal`): its figures are not yet checked on customers'
    // кабинеты. Both grants, because ДРР divides «Мониторинг» spend by
    // «Отчёты» sales.
    path: '/advertising',
    name: 'advertising',
    component: () => import('@/modules/advertising/views/AdvertisingView.vue'),
    meta: {
      title: 'Реклама',
      requiresAuth: true,
      requiresInternal: true,
      modules: ['monitoring', 'finreports'],
    },
  },
]
