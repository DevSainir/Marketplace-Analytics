/** Route table owned by the summary module; exported via the Public API. */
export const summaryRoutes = [
  {
    // A product surface, and the replacement for «Сравнение SKU»: the same
    // question — how is the кабинет doing — answered in money rather than in
    // lines. Behind its own grant since 2026-10-12, like the API
    // (`require_summary`); it asked for both «Мониторинг» and P&L before.
    path: '/summary',
    name: 'summary',
    component: () => import('@/modules/summary/views/SummaryView.vue'),
    meta: { title: 'Сводка', requiresAuth: true, module: 'summary' },
  },
]
