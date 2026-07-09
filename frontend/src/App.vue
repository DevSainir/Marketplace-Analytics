<script setup>
import { RouterLink, RouterView, useRouter } from 'vue-router'

import { useAuthStore } from '@/modules/auth'

const auth = useAuthStore()
const router = useRouter()

async function onLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="flex min-h-screen flex-col">
    <header class="sticky top-0 z-20 border-b border-slate-200 bg-white/80 backdrop-blur">
      <nav
        class="mx-auto flex h-14 w-full max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8"
      >
        <RouterLink to="/" class="flex items-center gap-2">
          <span
            class="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white"
            >М</span
          >
          <span class="text-sm font-semibold tracking-tight text-slate-900"
            >Аналитика маркетплейса</span
          >
        </RouterLink>

        <div class="flex items-center gap-1">
          <RouterLink
            to="/"
            class="rounded-lg px-3 py-1.5 text-sm font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
            exact-active-class="bg-slate-100 text-slate-900"
          >
            Главная
          </RouterLink>
          <RouterLink
            to="/monitoring"
            class="rounded-lg px-3 py-1.5 text-sm font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
            active-class="bg-slate-100 text-slate-900"
          >
            Мониторинг
          </RouterLink>

          <span class="mx-1 h-5 w-px bg-slate-200" aria-hidden="true"></span>

          <template v-if="auth.isAuthenticated">
            <span class="hidden max-w-48 truncate text-sm text-slate-400 sm:inline">
              {{ auth.userEmail }}
            </span>
            <button
              type="button"
              class="rounded-lg px-3 py-1.5 text-sm font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
              @click="onLogout"
            >
              Выйти
            </button>
          </template>
          <RouterLink
            v-else
            to="/login"
            class="rounded-lg px-3 py-1.5 text-sm font-medium text-indigo-600 transition hover:bg-indigo-50"
            active-class="bg-indigo-50"
          >
            Войти
          </RouterLink>
        </div>
      </nav>
    </header>

    <main class="flex-1">
      <RouterView />
    </main>
  </div>
</template>
