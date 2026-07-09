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
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [...coreRoutes, ...authRoutes, ...monitoringRoutes],
})

export default router
