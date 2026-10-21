/** Route table owned by the advertising module; exported via the Public API. */
export const advertisingRoutes = [
  {
    // Every subscriber since 2026-10-10, behind the «Реклама» grant like the
    // API behind it (`require_advertising`). Its own switch rather than
    // «Мониторинг»'s: the page shows sales and DRR from sales.
    path: '/advertising',
    name: 'advertising',
    component: () => import('@/modules/advertising/views/AdvertisingView.vue'),
    meta: { title: 'Реклама', requiresAuth: true, module: 'advertising' },
  },
]
