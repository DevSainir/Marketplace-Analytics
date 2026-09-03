<script setup>
/**
 * What a registered account sees before it belongs to a company.
 *
 * Registration is open, and `require_member` closes everything behind it, so
 * there is a real state between "signed up" and "inside a company": the session
 * is valid, `/v1/auth/me` answers, and every tenant-scoped call returns 403.
 * The app used to render its whole shell in that state with every panel empty
 * and nothing saying why — which reads as a broken account rather than an
 * unfinished one, and the person has no way to tell the difference.
 *
 * So the page behind is blurred and made inert, and the card in front carries
 * the one thing that changes the situation: the activation code.
 *
 * **The header is deliberately NOT blurred.** It is outside this component, and
 * it must stay usable — somebody who cannot activate needs to be able to log
 * out, and trapping them behind a form they cannot complete is worse than
 * showing them an empty app.
 *
 * The blur is presentation only. The API refuses these surfaces on its own;
 * nothing here is a security control, and it is not written as one.
 */
import { RouterLink } from 'vue-router'

import ActivationKeyForm from '@/modules/profile/components/ActivationKeyForm.vue'
import { useMembersStore } from '@/modules/profile/membersStore'

const members = useMembersStore()
</script>

<template>
  <div class="relative">
    <!-- `inert` is the load-bearing half: without it the blurred page still
         takes Tab focus, so a keyboard user lands in inputs they cannot see. -->
    <div :class="members.hasOrganization ? '' : 'gate-blurred'" :inert="!members.hasOrganization">
      <slot />
    </div>

    <div v-if="!members.hasOrganization" class="gate-overlay">
      <section class="gate-card">
        <h2 class="text-h2 font-bold tracking-tight text-primary">Нужен ключ активации</h2>
        <p class="mt-xs text-tiny font-medium text-muted">
          Аккаунт создан, но ещё не привязан к компании. Введите ключ активации — или
          <RouterLink class="gate-link" :to="{ name: 'invite' }">примите приглашение</RouterLink>,
          если владелец компании вам его прислал.
        </p>

        <ActivationKeyForm class="mt-md" />
      </section>
    </div>
  </div>
</template>

<style scoped>
.gate-blurred {
  filter: blur(6px);
  /* The page underneath is decoration now. Desaturating it stops the numbers
     reading as real figures somebody might squint at and act on. */
  opacity: 0.55;
  user-select: none;
  pointer-events: none;
}

.gate-overlay {
  @apply absolute inset-0 flex items-start justify-center px-md;
  /* Not centred on the viewport: the card sits near the top of the content it
     covers, where the eye already is after a navigation. */
  padding-top: clamp(48px, 12vh, 160px);
}

.gate-link {
  font-weight: 600;
  color: var(--ui-action);
}

.gate-link:hover {
  color: var(--ui-action-hover);
}

.gate-card {
  @apply w-full max-w-md rounded-card border border-border-subtle p-lg text-center shadow-card;
  /* Opaque, not glass. `ui-next` puts glass on chrome that floats over content;
     a panel whose whole job is to be readable against a blurred page is the one
     place the design system says NOT to use it. */
  background-color: var(--ui-surface);
}

.gate-input {
  @apply h-10 w-full rounded-input border border-border-subtle bg-canvas px-md text-center text-base text-primary placeholder:text-muted focus:outline-none focus:ring-2 phone:h-11;
}

.gate-input:focus {
  border-color: var(--ui-action);
}

.gate-error {
  @apply rounded-input border px-md py-sm text-tiny font-medium;
  border-color: color-mix(in srgb, var(--ui-neg) 30%, transparent);
  background-color: color-mix(in srgb, var(--ui-neg) 10%, transparent);
  color: var(--ui-neg);
}

.gate-button {
  @apply inline-flex h-10 w-full items-center justify-center rounded-btn text-base font-semibold text-white shadow-soft transition disabled:cursor-not-allowed disabled:opacity-60 phone:h-11;
  background-color: var(--ui-action);
}

.gate-button:hover:not(:disabled) {
  background-color: var(--ui-action-hover);
}
</style>
