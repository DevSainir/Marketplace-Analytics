<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/modules/auth/store'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

// 'ask' → the address; 'redeem' → the code and the new password; 'done' → sent
// to the login screen. One view rather than three routes: the code is only
// useful in the browser that asked for it, so a deep link to step two would
// mostly be a dead end.
const step = ref('ask')
const email = ref(typeof route.query.email === 'string' ? route.query.email : '')
const code = ref('')
const newPassword = ref('')

const heading = computed(() => (step.value === 'done' ? 'Пароль изменён' : 'Восстановление пароля'))

async function requestCode() {
  // True means "accepted", NOT "that address exists" — the backend answers the
  // same way either way, and showing anything else here would turn this form
  // into the account-existence oracle /login is careful not to be.
  if (await auth.askForPasswordReset(email.value)) {
    step.value = 'redeem'
  }
}

async function submitNewPassword() {
  if (await auth.resetPassword(email.value, code.value, newPassword.value)) {
    step.value = 'done'
  }
}

function goToLogin() {
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="app-container py-16 phone:py-lg sm:py-24">
    <div class="mx-auto flex w-full max-w-md flex-col">
      <header class="text-center">
        <h1 class="text-h2 font-bold tracking-tight text-primary">{{ heading }}</h1>
        <p class="mt-xs text-tiny font-medium text-muted">
          <template v-if="step === 'ask'">
            Отправим код на вашу почту. Код действует ограниченное время.
          </template>
          <template v-else-if="step === 'redeem'">
            Если аккаунт с такой почтой существует, письмо с кодом уже отправлено.
          </template>
          <template v-else>
            Все сессии этого аккаунта завершены — войдите с новым паролем.
          </template>
        </p>
      </header>

      <section class="mt-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card">
        <form v-if="step === 'ask'" class="flex flex-col gap-md" @submit.prevent="requestCode">
          <label class="block">
            <span class="mb-xs block text-tiny font-medium text-muted">Электронная почта</span>
            <input
              v-model="email"
              type="email"
              required
              autocomplete="email"
              placeholder="manager@company.ru"
              class="auth-input"
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
            {{ auth.loading ? 'Подождите…' : 'Отправить код' }}
          </button>
        </form>

        <form
          v-else-if="step === 'redeem'"
          class="flex flex-col gap-md"
          @submit.prevent="submitNewPassword"
        >
          <label class="block">
            <span class="mb-xs block text-tiny font-medium text-muted">Код из письма</span>
            <input
              v-model="code"
              inputmode="numeric"
              autocomplete="one-time-code"
              required
              placeholder="123456"
              class="auth-input tracking-[0.4em]"
            />
          </label>

          <label class="block">
            <span class="mb-xs block text-tiny font-medium text-muted">Новый пароль</span>
            <input
              v-model="newPassword"
              type="password"
              required
              minlength="8"
              autocomplete="new-password"
              placeholder="••••••••"
              class="auth-input"
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
            {{ auth.loading ? 'Подождите…' : 'Сохранить пароль' }}
          </button>

          <button
            type="button"
            class="text-tiny font-medium text-action transition hover:text-action-hover"
            @click="requestCode"
          >
            Отправить код ещё раз
          </button>
        </form>

        <div v-else class="flex flex-col gap-md">
          <button
            type="button"
            class="inline-flex h-10 w-full items-center justify-center gap-sm rounded-btn bg-action text-base font-semibold text-white shadow-soft transition hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-60 phone:h-11"
            @click="goToLogin"
          >
            Войти
          </button>
        </div>
      </section>

      <p class="mt-lg text-center text-tiny text-muted">
        <RouterLink
          class="text-tiny font-medium text-action transition hover:text-action-hover"
          :to="{ name: 'login' }"
          >Вернуться ко входу</RouterLink
        >
      </p>
    </div>
  </div>
</template>

<style scoped>
/* Only the input recipe, and only because LoginView keeps the same one — three
   auth pages that differ by a shade read as a bug.
   Everything else stays inline DELIBERATELY: a scoped rule carries a
   `[data-v-*]` attribute and outranks `ui-next/skin.css`, so `@apply bg-action`
   in here resolves the pre-skin teal from tailwind.config while the identical
   utility in the markup resolves the skinned violet. Measured, not assumed —
   the link this replaced rendered #007E76 beside a #715FFF button. */
.auth-input {
  @apply h-10 w-full rounded-input border border-border-subtle bg-canvas px-md text-base text-primary placeholder:text-muted focus:border-action focus:outline-none focus:ring-2 focus:ring-action/20 phone:h-11;
}
</style>
