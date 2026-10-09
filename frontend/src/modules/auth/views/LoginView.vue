<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { safeRedirect } from '@/modules/auth/guard'
import PasswordField from '@/core/components/PasswordField.vue'
import PasswordRules from '@/modules/auth/components/PasswordRules.vue'
import { useAuthStore } from '@/modules/auth/store'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

// Initial tab can be deep-linked from the header (`/login?mode=register`).
const mode = ref(route.query.mode === 'register' ? 'register' : 'login') // 'login' | 'register'
// Prefilled when «Изменить почту» sends someone back from the code screen:
// they are correcting a typo, and retyping the whole address to fix one letter
// is how the typo happens again.
const email = ref(typeof route.query.email === 'string' ? route.query.email : '')
const password = ref('')
// Registration is invite-only: the backend rejects /register without a valid
// operator-issued code (the platform exposes the whole seller account's data).

const isLogin = computed(() => mode.value === 'login')

function switchMode(next) {
  mode.value = next
  auth.clearError()
}

/**
 * Send an unconfirmed address to the code screen.
 *
 * `requestCode` is NOT a convenience flag — getting it wrong mails two codes,
 * and the second silently kills the first (issuing a code invalidates the
 * previous one, by design). So it is false on the one path that has already
 * sent one: a successful `/register`, which mails the code itself. Every other
 * way in — a login refused as unconfirmed, a repeat signup refused the same
 * way — reaches here with nothing sent, and has to ask.
 */
function goConfirm({ requestCode }) {
  if (requestCode) auth.askForConfirmationCode(email.value)
  router.push({
    name: 'confirm-email',
    query: { email: email.value, redirect: route.query.redirect },
  })
}

async function submit() {
  if (isLogin.value) {
    if (await auth.login(email.value, password.value)) {
      // A full page load, NOT `router.push`. Signing in is an SPA action, so
      // every Pinia store survived it — and after signing out and in as
      // somebody else, the previous account's workspaces and their P&L figures
      // were still on screen, rendered from memory. The server never sent them
      // (it refuses another tenant's workspace), but whoever sits down next
      // reads them. The reload is the same guarantee the workspace switcher
      // relies on: nothing cached survives it.
      window.location.assign(safeRedirect(route.query.redirect))
      return
    }
    // The password was right and the address was never proven — an unfinished
    // signup coming back. `/login` sends no code, so ask for one.
    if (auth.needsConfirmation) goConfirm({ requestCode: true })
    return
  }

  // Registration creates the account and mails a code, but issues NO session:
  // leaving this screen means not being logged in, which is what makes an
  // abandoned signup harmless. `register` resolves true once the code is on its
  // way; a repeat signup for an address that never confirmed lands in the same
  // place rather than on "already exists".
  // `/register` answers the same way for a fresh signup and for one resuming an
  // address that was never confirmed — it mails a code either way, so there is
  // one branch here and it must NOT ask for a second.
  if (await auth.register(email.value, password.value)) {
    goConfirm({ requestCode: false })
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
            <PasswordField
              v-model="password"
              :autocomplete="isLogin ? 'current-password' : 'new-password'"
            />
            <!-- Registration only: on the login tab the rules are advice about
                 a password the person already has, which is just noise. -->
            <PasswordRules v-if="!isLogin" :value="password" />
          </label>

          <p
            v-if="auth.error"
            class="rounded-input border border-status-negative/30 bg-status-negative/10 px-md py-sm text-base font-medium text-status-negative"
          >
            {{ auth.error }}
            <!-- The account being refused is almost always the person's own:
                 registration creates it before the address is confirmed, so
                 abandoning that step and coming back lands exactly here. A
                 message they cannot act on is what makes it a dead end. -->
            <button
              v-if="auth.emailTaken"
              type="button"
              class="mt-xs block font-semibold underline"
              @click="switchMode('login')"
            >
              Перейти ко входу
            </button>
          </p>

          <button type="submit" :disabled="auth.loading" class="ui-btn ui-btn--primary w-full">
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

        <p v-if="isLogin" class="mt-md text-center">
          <RouterLink
            class="text-tiny font-medium text-action transition hover:text-action-hover"
            :to="{ name: 'password-reset' }"
          >
            Забыли пароль?
          </RouterLink>
        </p>
      </section>
    </div>
  </div>
</template>

<style scoped>
/* Two recipes repeated across the form; everything else stays inline. */
.login-tab {
  @apply rounded-btn px-md py-xs text-base font-medium text-muted transition hover:text-primary phone:min-h-11;
}

.login-tab--active {
  @apply bg-action text-white shadow-soft hover:text-white;
}

.login-input {
  @apply h-10 w-full rounded-input border border-border-subtle bg-canvas px-md text-base text-primary placeholder:text-muted focus:border-action focus:outline-none focus:ring-2 focus:ring-action/20 phone:h-11;
}
</style>
