/** Route table owned by the profile module; exported via the Public API. */
export const profileRoutes = [
  {
    path: '/profile',
    name: 'profile',
    component: () => import('@/modules/profile/views/ProfileView.vue'),
    // Never gated by ActivationGate: an account waiting for a code still
    // needs to read its own email and role, and blurring the one page that
    // explains who you are is how a new user ends up with nowhere to go.
    meta: { title: 'Профиль', requiresAuth: true, allowWithoutOrganization: true },
  },
]
