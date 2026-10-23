<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import CodeInput from '@/core/components/CodeInput.vue'
import PasswordField from '@/core/components/PasswordField.vue'
import PasswordRules from '@/modules/auth/components/PasswordRules.vue'
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

const heading = computed(() => (step.value === 'done' ? 'Password changed' : 'Reset password'))

async function requestCode() {
  // True means "accepted", NOT "that address exists" — the backend answers the
  // same way either way, and showing anything else here would turn this form
  // into the account-existence oracle /login is careful not to be.
  if (await auth.askForPasswordReset(email.value)) {
    step.value = 'redeem'
  }
}

async function submitNewPassword() {
  // The button and CodeInput's `complete` both land here; without the guard a
  // fast typist spends two of the five attempts the backend allows.
  if (auth.loading || code.value.length < 6) return
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
            We'll email you a code. It is valid for a limited time.
          </template>
          <template v-else-if="step === 'redeem'">
            If an account with this email exists, a code is on its way.
          </template>
          <template v-else>
            Every session of this account has ended. Sign in with the new password.
          </template>
        </p>
      </header>

      <section class="mt-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card">
        <form v-if="step === 'ask'" class="flex flex-col gap-md" @submit.prevent="requestCode">
          <label class="block">
            <span class="mb-xs block text-tiny font-medium text-muted">Email</span>
            <input
              v-model="email"
              type="email"
              required
              autocomplete="email"
              placeholder="manager@company.com"
              class="ui-input w-full"
            />
          </label>

          <p
            v-if="auth.error"
            class="rounded-input border border-status-negative/30 bg-status-negative/10 px-md py-sm text-base font-medium text-status-negative"
          >
            {{ auth.error }}
          </p>

          <button type="submit" :disabled="auth.loading" class="ui-btn ui-btn--primary w-full">
            {{ auth.loading ? 'Working…' : 'Send code' }}
          </button>
        </form>

        <form
          v-else-if="step === 'redeem'"
          class="flex flex-col gap-md"
          @submit.prevent="submitNewPassword"
        >
          <div>
            <span class="mb-sm block text-center text-tiny font-medium text-muted">
              Code from the email
            </span>
            <CodeInput
              v-model="code"
              autofocus
              :invalid="Boolean(auth.error)"
              :disabled="auth.loading"
            />
          </div>

          <label class="block">
            <span class="mb-xs block text-tiny font-medium text-muted">New password</span>
            <PasswordField v-model="newPassword" autocomplete="new-password" />
            <PasswordRules :value="newPassword" />
          </label>

          <p
            v-if="auth.error"
            class="rounded-input border border-status-negative/30 bg-status-negative/10 px-md py-sm text-base font-medium text-status-negative"
          >
            {{ auth.error }}
          </p>

          <button type="submit" :disabled="auth.loading" class="ui-btn ui-btn--primary w-full">
            {{ auth.loading ? 'Working…' : 'Save password' }}
          </button>

          <!-- `self-center`: a <button> in a flex COLUMN stretches to the full
               row, so hovering anywhere on the line lit the text up. -->
          <button type="button" class="auth-link self-center" @click="requestCode">
            Resend code
          </button>
        </form>

        <div v-else class="flex flex-col gap-md">
          <button type="button" class="ui-btn ui-btn--primary w-full" @click="goToLogin">
            Sign in
          </button>
        </div>
      </section>

      <p class="mt-lg text-center text-tiny text-muted">
        <RouterLink
          class="text-tiny font-medium text-action transition hover:text-action-hover"
          :to="{ name: 'login' }"
          >Back to sign in</RouterLink
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
</style>
