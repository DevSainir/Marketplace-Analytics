<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { safeRedirect } from '@/modules/auth/guard'
import { useAuthStore } from '@/modules/auth/store'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

// The address comes from the query when registration sends the user here, and
// falls back to the one the session already knows. Editable either way: the
// commonest reason to be on this screen with no code is a typo in the address.
const email = ref(
  typeof route.query.email === 'string' ? route.query.email : (auth.userEmail ?? ''),
)
const code = ref('')
const confirmed = ref(false)
const resent = ref(false)

async function submit() {
  if (await auth.confirmAddress(email.value, code.value)) {
    confirmed.value = true
  }
}

async function resend() {
  resent.value = await auth.askForConfirmationCode(email.value)
}

function goOn() {
  // Confirmation is not a login gate — the account is already signed in by the
  // time it lands here — so "later" and "done" go to the same place, and both
  // honour whatever the user was originally trying to reach.
  router.push(safeRedirect(route.query.redirect))
}
</script>

<template>
  <div class="app-container py-16 phone:py-lg sm:py-24">
    <div class="mx-auto flex w-full max-w-md flex-col">
      <header class="text-center">
        <h1 class="text-h2 font-bold tracking-tight text-primary">
          {{ confirmed ? 'Почта подтверждена' : 'Подтвердите почту' }}
        </h1>
        <p class="mt-xs text-tiny font-medium text-muted">
          <template v-if="confirmed">
            Теперь можно активировать доступ или принять приглашение в компанию.
          </template>
          <template v-else>
            Мы отправили код на вашу почту. Подтверждение нужно, чтобы активировать доступ или
            принять приглашение — войти в аккаунт можно и без него.
          </template>
        </p>
      </header>

      <section class="mt-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card">
        <form v-if="!confirmed" class="flex flex-col gap-md" @submit.prevent="submit">
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

          <p
            v-if="auth.error"
            class="rounded-input border border-status-negative/30 bg-status-negative/10 px-md py-sm text-base font-medium text-status-negative"
          >
            {{ auth.error }}
          </p>
          <!-- Deliberately not "the code was sent to that address": the endpoint
               answers the same way for an address that does not exist, and this
               screen must not become the oracle the backend refuses to be. -->
          <p v-else-if="resent" class="text-tiny font-medium text-muted">
            Если аккаунт с такой почтой существует, новый код отправлен.
          </p>

          <button
            type="submit"
            :disabled="auth.loading"
            class="inline-flex h-10 w-full items-center justify-center gap-sm rounded-btn bg-action text-base font-semibold text-white shadow-soft transition hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-60 phone:h-11"
          >
            {{ auth.loading ? 'Подождите…' : 'Подтвердить' }}
          </button>

          <button
            type="button"
            class="text-tiny font-medium text-action transition hover:text-action-hover"
            @click="resend"
          >
            Отправить код ещё раз
          </button>
        </form>

        <button
          v-else
          type="button"
          class="inline-flex h-10 w-full items-center justify-center gap-sm rounded-btn bg-action text-base font-semibold text-white shadow-soft transition hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-60 phone:h-11"
          @click="goOn"
        >
          Продолжить
        </button>
      </section>

      <p v-if="!confirmed" class="mt-lg text-center text-tiny text-muted">
        <button
          type="button"
          class="text-tiny font-medium text-action transition hover:text-action-hover"
          @click="goOn"
        >
          Подтвердить позже
        </button>
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
