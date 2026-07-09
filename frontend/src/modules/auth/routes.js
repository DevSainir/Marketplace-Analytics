/** Route table owned by the auth module; exported via the Public API. */
export const authRoutes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/modules/auth/views/LoginView.vue'),
    // Authenticated users have no business on the login page.
    meta: { title: 'Вход', guestOnly: true },
  },
]
