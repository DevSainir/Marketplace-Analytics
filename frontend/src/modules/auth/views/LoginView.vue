<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { safeRedirect } from '@/modules/auth/guard'
import { useAuthStore } from '@/modules/auth/store'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const mode = ref('login') // 'login' | 'register'
const email = ref('')
const password = ref('')

const isLogin = computed(() => mode.value === 'login')

function switchMode(next) {
  mode.value = next
  auth.error = null
}

async function submit() {
  const ok = isLogin.value
    ? await auth.login(email.value, password.value)
    : await auth.register(email.value, password.value)

  if (ok) {
    router.push(safeRedirect(route.query.redirect))
  }
}
</script>

<template>
  <div class="mx-auto flex w-full max-w-md flex-col px-4 py-16 sm:py-24">
    <header class="text-center">
      <h1 class="text-2xl font-bold tracking-tight text-slate-900">
        {{ isLogin ? 'Вход в аккаунт' : 'Регистрация' }}
      </h1>
      <p class="mt-2 text-sm text-slate-500">
        {{
          isLogin
            ? 'Введите почту и пароль, чтобы продолжить.'
            : 'Создайте аккаунт менеджера, чтобы получить доступ к аналитике.'
        }}
      </p>
    </header>

    <!-- Mode switch -->
    <div
      class="mt-8 grid grid-cols-2 rounded-lg border border-slate-200 bg-slate-50 p-1 text-sm font-medium"
    >
      <button
        type="button"
        class="rounded-md px-3 py-1.5 transition"
        :class="
          isLogin ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-900'
        "
        @click="switchMode('login')"
      >
        Вход
      </button>
      <button
        type="button"
        class="rounded-md px-3 py-1.5 transition"
        :class="
          !isLogin ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-900'
        "
        @click="switchMode('register')"
      >
        Регистрация
      </button>
    </div>

    <form
      class="mt-6 space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
      @submit.prevent="submit"
    >
      <label class="block">
        <span class="mb-1.5 block text-sm font-medium text-slate-700">Электронная почта</span>
        <input
          v-model="email"
          type="email"
          required
          autocomplete="email"
          placeholder="manager@company.ru"
          class="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-600/20"
        />
      </label>

      <label class="block">
        <span class="mb-1.5 block text-sm font-medium text-slate-700">Пароль</span>
        <input
          v-model="password"
          type="password"
          required
          minlength="8"
          :autocomplete="isLogin ? 'current-password' : 'new-password'"
          placeholder="••••••••"
          class="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-600/20"
        />
      </label>

      <p
        v-if="auth.error"
        class="rounded-lg border border-rose-500/20 bg-rose-50 px-3 py-2 text-sm text-rose-500"
      >
        {{ auth.error }}
      </p>

      <button
        type="submit"
        :disabled="auth.loading"
        class="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
      >
        <svg
          v-if="auth.loading"
          class="h-4 w-4 animate-spin"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.5"
          stroke-linecap="round"
        >
          <path d="M12 3a9 9 0 1 0 9 9" />
        </svg>
        {{ auth.loading ? 'Подождите…' : isLogin ? 'Войти' : 'Создать аккаунт' }}
      </button>
    </form>

    <p class="mt-6 text-center text-xs text-slate-400">
      Сессия продлевается автоматически через защищённый HttpOnly-cookie.
    </p>
  </div>
</template>
