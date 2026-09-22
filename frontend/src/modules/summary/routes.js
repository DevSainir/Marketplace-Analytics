/** Route table owned by the summary module; exported via the Public API. */
export const summaryRoutes = [
  {
    // A product surface, and the replacement for «Сравнение SKU»: the same
    // question — how is the кабинет doing — answered in money rather than in
    // lines. Reachable by every paying кабинет; the API asks for BOTH module
    // grants, because the page puts the settlement's revenue beside
    // monitoring's orders.
    path: '/summary',
    name: 'summary',
    component: () => import('@/modules/summary/views/SummaryView.vue'),
    meta: { title: 'Сводка', requiresAuth: true, modules: ['monitoring', 'finreports'] },
  },
]
