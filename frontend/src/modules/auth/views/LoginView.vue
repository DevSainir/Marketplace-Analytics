<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { safeRedirect } from '@/modules/auth/guard'
import { useAuthStore } from '@/modules/auth/store'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

// Initial tab can be deep-linked from the header (`/login?mode=register`).
const mode = ref(route.query.mode === 'register' ? 'register' : 'login') // 'login' | 'register'
const email = ref('')
const password = ref('')
// Registration is invite-only: the backend rejects /register without a valid
// operator-issued code (the platform exposes the whole seller account's data).
const inviteCode = ref('')

const isLogin = computed(() => mode.value === 'login')

function switchMode(next) {
  mode.value = next
  auth.clearError()
}

async function submit() {
  const ok = isLogin.value
    ? await auth.login(email.value, password.value)
    : await auth.register(email.value, password.value, inviteCode.value)

  if (ok) {
    router.push(safeRedirect(route.query.redirect))
  }
}
</script>

<template>
  <!-- `.app-container` gives the safe-area gutter; the inner max-w-md is the
       form's own comfortable measure (see main.css / the phone-layout skill). -->
  <div class="app-container py-16 phone:py-lg sm:py-24">
    <div class="mx-auto flex w-full max-w-md flex-col">
      <header class="text-center">
        <h1 class="text-h2 font-bold tracking-tight text-primary">
          {{ isLogin ? 'Вход в аккаунт' : 'Регистрация' }}
        </h1>
        <p class="mt-xs text-tiny font-medium text-muted">
          {{
            isLogin
              ? 'Введите почту и пароль, чтобы продолжить.'
              : 'Создайте аккаунт менеджера, чтобы получить доступ к аналитике.'
          }}
        </p>
      </header>

      <!-- One card: the mode switch is part of the form, not a control floating
           on the canvas. Its track is `bg-canvas` — recessed inside a surface,
           which is the only way a segmented control reads on this plane. -->
      <section class="mt-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card">
        <div class="grid grid-cols-2 gap-xs rounded-btn bg-canvas p-xs">
          <button
            type="button"
            class="login-tab"
            :class="isLogin ? 'login-tab--active' : ''"
            @click="switchMode('login')"
          >
            Вход
          </button>
          <button
            type="button"
            class="login-tab"
            :class="!isLogin ? 'login-tab--active' : ''"
            @click="switchMode('register')"
          >
            Регистрация
          </button>
        </div>

        <form class="mt-md flex flex-col gap-md" @submit.prevent="submit">
          <label class="block">
            <span class="mb-xs block text-tiny font-medium text-muted">Электронная почта</span>
            <input
              v-model="email"
              type="email"
              required
              autocomplete="email"
              placeholder="manager@company.ru"
              class="login-input"
            />
          </label>

          <label class="block">
            <span class="mb-xs block text-tiny font-medium text-muted">Пароль</span>
            <input
              v-model="password"
              type="password"
              required
              minlength="8"
              :autocomplete="isLogin ? 'current-password' : 'new-password'"
              placeholder="••••••••"
              class="login-input"
            />
          </label>

          <label v-if="!isLogin" class="block">
            <span class="mb-xs block text-tiny font-medium text-muted">Код приглашения</span>
            <input
              v-model="inviteCode"
              type="text"
              required
              autocomplete="off"
              placeholder="Выдаётся администратором"
              class="login-input"
            />
          </label>

          <p
            v-if="auth.error"
            class="rounded-input border border-status-negative/30 bg-status-negative/10 px-md py-sm text-base font-medium text-status-negative"
          >
            {{ auth.error }}
          </p>

          <button
            type="submit"
            :disabled="auth.loading"
            class="inline-flex h-10 w-full items-center justify-center gap-sm rounded-btn bg-action text-base font-semibold text-white shadow-soft transition hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-60 phone:h-11"
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
      </section>

      <p class="mt-lg text-center text-tiny text-muted">
        Сессия продлевается автоматически через защищённый HttpOnly-cookie.
      </p>
    </div>
  </div>
</template>

<style scoped>
/* Two recipes repeated across the form; everything else stays inline. */
.login-tab {
  @apply rounded-btn px-md py-xs text-base font-medium text-muted transition hover:text-primary phone:min-h-11;
}

.login-tab--active {
  @apply bg-surface text-primary shadow-soft;
}

.login-input {
  @apply h-10 w-full rounded-input border border-border-subtle bg-canvas px-md text-base text-primary placeholder:text-muted focus:border-action focus:outline-none focus:ring-2 focus:ring-action/20 phone:h-11;
}
</style>
