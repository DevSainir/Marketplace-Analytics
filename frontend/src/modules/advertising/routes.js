/** Route table owned by the advertising module; exported via the Public API. */
export const advertisingRoutes = [
  {
    // Internal while it is being built, like the API behind it
    // (`require_internal`): its figures are not yet checked on customers'
    // кабинеты. «Мониторинг» only: every member of our organisation reads the
    // whole page, sales included (the owner's decision of 2026-10-07).
    path: '/advertising',
    name: 'advertising',
    component: () => import('@/modules/advertising/views/AdvertisingView.vue'),
    meta: {
      title: 'Реклама',
      requiresAuth: true,
      requiresInternal: true,
      modules: ['monitoring'],
    },
  },
]
