/**
 * Centralized router.
 *
 * Module route arrays are aggregated STRICTLY from each module's Public API
 * (`@/modules/<name>` → index.js). Importing a module's internal `routes.js`
 * directly is an architectural violation enforced by ESLint.
 */
import { createRouter, createWebHistory } from 'vue-router'

import { authRoutes } from '@/modules/auth'
import { monitoringRoutes } from '@/modules/monitoring'

const coreRoutes = [
  {
    path: '/',
    name: 'home',
    component: () => import('@/core/views/HomeView.vue'),
  },
  // Catch-all: any unknown path renders a friendly 404 instead of a blank app.
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/core/views/NotFoundView.vue'),
    meta: { title: 'Страница не найдена' },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [...coreRoutes, ...authRoutes, ...monitoringRoutes],
})

// Keep the tab title in sync with the route (`meta.title` is per-module data).
const BASE_TITLE = 'Аналитика маркетплейса'

router.afterEach((to) => {
  document.title = to.meta.title
    ? `${to.meta.title} — ${BASE_TITLE}`
    : `${BASE_TITLE} — Wildberries`
})

export default router
