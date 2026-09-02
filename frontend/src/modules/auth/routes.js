/** Route table owned by the auth module; exported via the Public API. */
export const authRoutes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/modules/auth/views/LoginView.vue'),
    // Authenticated users have no business on the login page.
    meta: { title: 'Вход', guestOnly: true },
  },
  {
    path: '/password-reset',
    name: 'password-reset',
    component: () => import('@/modules/auth/views/PasswordResetView.vue'),
    // Guest-only for the same reason as /login: somebody already signed in
    // changes their password from the profile, not from a mailed code.
    meta: { title: 'Восстановление пароля', guestOnly: true },
  },
  {
    path: '/confirm-email',
    name: 'confirm-email',
    component: () => import('@/modules/auth/views/EmailConfirmView.vue'),
    // NOT guest-only, and not `requiresAuth` either. Registration signs the
    // account in and then sends it here, so a guest-only guard would bounce
    // every new user straight off the screen they were just given; and someone
    // who confirms from a different browser has no session to require.
    meta: { title: 'Подтверждение почты' },
  },
]
