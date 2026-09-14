/** Route table owned by the labs module; exported via the Public API. */
export const labsRoutes = [
  {
    // Deliberately not behind `requiresAuth`: the page renders fixtures, has no
    // API calls, and being able to open it without a session is the point of a
    // design sandbox.
    path: '/labs/monitoring',
    name: 'labs-monitoring',
    component: () => import('@/modules/labs/views/LabMonitoringView.vue'),
    meta: { title: 'Мониторинг · Lab', requiresAuth: true, requiresInternal: true },
  },
  {
    // This one DOES call the API — it is the profile page relaid out, running
    // on the real stores so the layout can be judged against real data (a
    // fixture team of three would prove nothing about a team of one). Same
    // internal-only gate as the rest of the labs.
    //
    // A parent with three children rather than one long page: the security
    // section alone (password, plus every device this account is signed in on)
    // is a screen, and three screens under one scrollbar is a page you scroll
    // past rather than one you navigate. The shell owns the rail and the
    // bootstrap; each child owns its own data.
    path: '/labs/profile',
    component: () => import('@/modules/labs/views/LabProfileLayout.vue'),
    meta: { requiresAuth: true, requiresInternal: true },
    children: [
      {
        path: '',
        name: 'labs-profile-general',
        component: () => import('@/modules/labs/views/LabProfileGeneral.vue'),
        meta: { title: 'Профиль · Lab', requiresAuth: true, requiresInternal: true },
      },
      {
        path: 'team',
        name: 'labs-profile-team',
        component: () => import('@/modules/labs/views/LabProfileTeam.vue'),
        meta: { title: 'Команда · Lab', requiresAuth: true, requiresInternal: true },
      },
      {
        path: 'security',
        name: 'labs-profile-security',
        component: () => import('@/modules/labs/views/LabProfileSecurity.vue'),
        meta: { title: 'Безопасность · Lab', requiresAuth: true, requiresInternal: true },
      },
    ],
  },
]
