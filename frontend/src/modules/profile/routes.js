/** Route table owned by the profile module; exported via the Public API. */
export const profileRoutes = [
  {
    path: '/profile',
    name: 'profile',
    component: () => import('@/modules/profile/views/ProfileView.vue'),
    meta: { title: 'Профиль', requiresAuth: true },
  },
]
