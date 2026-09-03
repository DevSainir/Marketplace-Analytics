<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import CodeInput from '@/core/components/CodeInput.vue'
import { safeRedirect } from '@/modules/auth/guard'
import { useAuthStore } from '@/modules/auth/store'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

// The address is NOT a field on this form any more. It arrives from the query
// when registration sends the user here, and falls back to the session's own.
// Asking for it again was asking a person to retype something we already know,
// beside a code that only we could have sent them.
const email = computed(() =>
  typeof route.query.email === 'string' ? route.query.email : (auth.userEmail ?? ''),
)
const code = ref('')
const confirmed = ref(false)
const resent = ref(false)

async function submit() {
  // `complete` fires on the sixth digit AND the button can be pressed, so both
  // paths land here; without this guard a fast typist submits twice and spends
  // two of the five attempts the backend allows.
  if (auth.loading || code.value.length < 6) return
  if (await auth.confirmAddress(email.value, code.value)) {
    confirmed.value = true
  } else {
    // A refused code is cleared rather than left in place: re-pressing with the
    // same digits burns another attempt for nothing. CodeInput refocuses the
    // first cell when the model empties.
    code.value = ''
  }
}

async function resend() {
  resent.value = await auth.askForConfirmationCode(email.value)
}

function changeEmail() {
  // Back to registration rather than "edit the address here". The account was
  // already created under the address on this screen, so a different one is a
  // different signup — editing a field in place would suggest otherwise.
  router.push({
    name: 'login',
    query: { mode: 'register', email: email.value, redirect: route.query.redirect },
  })
}

function goOn() {
  // Straight into the app: `/confirm-email` signed us in, so there is no login
  // step left to send anyone to. Honours whatever they were originally trying
  // to reach.
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
          <template v-if="confirmed"> Вы вошли в аккаунт. </template>
          <template v-else> Мы отправили код на вашу почту. </template>
        </p>
      </header>

      <section class="mt-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card">
        <!-- No address, no form: submitting would fail on a value the person
             cannot see or correct from here. -->
        <div v-if="!confirmed && !email" class="flex flex-col gap-md text-center">
          <p class="text-base text-muted">
            Не удалось определить, какую почту подтверждать. Начните вход или регистрацию заново.
          </p>
          <RouterLink class="auth-primary" :to="{ name: 'login' }">Войти</RouterLink>
        </div>

        <form v-else-if="!confirmed" class="flex flex-col gap-md" @submit.prevent="submit">
          <!-- Shown, not editable: the code was mailed to THIS address, so
               changing it here could only ever invalidate the code being
               typed. Seeing it is what catches the typo; «Изменить почту»
               is what fixes it. -->
          <div class="flex flex-col items-center gap-xs">
            <span class="text-tiny font-medium text-muted">Код отправлен на</span>
            <span class="max-w-full truncate text-base font-semibold text-primary">
              {{ email }}
            </span>
            <button type="button" class="auth-link" @click="changeEmail">Изменить почту</button>
          </div>

          <div>
            <span class="mb-sm block text-center text-tiny font-medium text-muted">
              Код из письма
            </span>
            <CodeInput
              v-model="code"
              autofocus
              :invalid="Boolean(auth.error)"
              :disabled="auth.loading"
              @complete="submit"
            />
          </div>

          <p
            v-if="auth.error"
            class="rounded-input border border-status-negative/30 bg-status-negative/10 px-md py-sm text-center text-base font-medium text-status-negative"
          >
            {{ auth.error }}
          </p>
          <!-- Deliberately not "the code was sent to that address": the endpoint
               answers the same way for an address that does not exist, and this
               screen must not become the oracle the backend refuses to be. -->
          <p v-else-if="resent" class="text-center text-tiny font-medium text-muted">
            Если аккаунт с такой почтой существует, новый код отправлен.
          </p>

          <button type="submit" :disabled="auth.loading || code.length < 6" class="auth-primary">
            {{ auth.loading ? 'Подождите…' : 'Подтвердить' }}
          </button>

          <!-- `self-center` is load-bearing: a <button> in a flex COLUMN
               stretches to the full row, so the hover state fired anywhere on
               the line, metres from the words. -->
          <button type="button" class="auth-link self-center" @click="resend">
            Отправить код ещё раз
          </button>
        </form>

        <button v-else type="button" class="auth-primary" @click="goOn">Продолжить</button>
      </section>
    </div>
  </div>
</template>

<style scoped>
/* Shared with LoginView and PasswordResetView — three auth pages that differ by
   a shade read as a bug.
   These stay HERE rather than becoming global utilities DELIBERATELY: a scoped
   rule carries a `[data-v-*]` attribute and outranks `ui-next/skin.css`, so
   `@apply bg-action` in here resolves the pre-skin teal from tailwind.config
   while the identical utility in the markup resolves the skinned violet.
   Measured, not assumed. `--ui-*` variables are read directly for that reason. */
.auth-primary {
  @apply inline-flex h-10 w-full items-center justify-center gap-sm rounded-btn text-base font-semibold text-white shadow-soft transition disabled:cursor-not-allowed disabled:opacity-60 phone:h-11;
  background-color: var(--ui-action);
}

.auth-primary:hover:not(:disabled) {
  background-color: var(--ui-action-hover);
}

.auth-link {
  @apply rounded-btn text-tiny font-medium transition;
  color: var(--ui-action);
}

.auth-link:hover {
  color: var(--ui-action-hover);
}
</style>
