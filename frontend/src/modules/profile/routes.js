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
    // A parent with three children rather than one long page. The security
    // section alone — the password, plus every device this account is signed
    // in on — is a screen, and three screens under one scrollbar is a page you
    // scroll past rather than one you navigate. The shell owns the rail and the
    // bootstrap; each child owns its own data.
    //
    // Never gated by ActivationGate: an account waiting for a code still needs
    // to read its own email and role, and this is where the code is entered.
    path: '/profile',
    component: () => import('@/modules/profile/views/ProfileView.vue'),
    meta: { requiresAuth: true, allowWithoutOrganization: true },
    children: [
      {
        path: '',
        // The parent used to carry this name, and half the app navigates by it
        // — the header's profile button, the guard's redirects, the e2e specs.
        // Moving it to the default child keeps every `{ name: 'profile' }`
        // working and lands it on «Общие».
        name: 'profile',
        component: () => import('@/modules/profile/views/ProfileGeneralView.vue'),
        meta: { title: 'Профиль', requiresAuth: true, allowWithoutOrganization: true },
      },
      {
        path: 'team',
        name: 'profile-team',
        component: () => import('@/modules/profile/views/ProfileTeamView.vue'),
        meta: { title: 'Команда', requiresAuth: true, allowWithoutOrganization: true },
      },
      {
        path: 'security',
        name: 'profile-security',
        component: () => import('@/modules/profile/views/ProfileSecurityView.vue'),
        meta: { title: 'Безопасность', requiresAuth: true, allowWithoutOrganization: true },
      },
      {
        // Dev only: the rail hides it from everyone else and the API refuses
        // them, so a non-dev who types the address gets an empty refusal.
        path: 'guests',
        name: 'profile-guests',
        component: () => import('@/modules/profile/views/ProfileGuestsView.vue'),
        meta: { title: 'Доступы', requiresAuth: true, allowWithoutOrganization: true },
      },
    ],
  },
]
