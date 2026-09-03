/** Route table owned by the profile module; exported via the Public API. */
export const profileRoutes = [
  {
    path: '/invite',
    name: 'invite',
    component: () => import('@/modules/profile/views/InviteAcceptView.vue'),
    // `allowWithoutOrganization`, obviously: this is how an account WITHOUT one
    // gets one. Blurring it behind the activation gate would hide the only
    // screen that resolves the state the gate is complaining about.
    meta: { title: 'Приглашение', requiresAuth: true, allowWithoutOrganization: true },
  },
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
