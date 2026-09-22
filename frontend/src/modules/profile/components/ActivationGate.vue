<script setup>
/**
 * What an account sees in front of a surface it cannot reach.
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
 * THREE refusals now share the blur, in priority order:
 *   1. the subscription is past its grace window — the paywall;
 *   2. the account belongs to no company — the activation key;
 *   3. the company has not granted this section — nothing to type.
 *
 * The paywall is first because it is the widest: it covers a person who IS in
 * a company and DOES have the section, and telling them about a module grant
 * when the company has simply stopped paying sends them to the wrong person.
 * It is also the one refusal that ignores `allowWithoutOrganization` — the
 * profile page stays legible to somebody waiting for a key, because there is
 * something there for them to do, but there is nothing on it for a lapsed
 * tenant that renewing does not fix first.
 *
 * **The header is deliberately NOT blurred.** It is outside this component, and
 * it must stay usable — somebody who cannot activate needs to be able to log
 * out, and trapping them behind a form they cannot complete is worse than
 * showing them an empty app.
 *
 * The blur is presentation only. The API refuses these surfaces on its own;
 * nothing here is a security control, and it is not written as one.
 */
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import ActivationKeyForm from '@/modules/profile/components/ActivationKeyForm.vue'
import { useMembersStore } from '@/modules/profile/membersStore'

const members = useMembersStore()
const route = useRoute()

// The routes that exist to RESOLVE being blocked — the profile page, the invite
// screen. They skip the first two refusals and never skip the paywall.
const isEscapeHatch = computed(() => Boolean(route.meta.allowWithoutOrganization))

// The subscription ran out. Covers every authenticated route, this component's
// own escape hatches included: past grace the API answers 403 everywhere, and
// an app that keeps rendering over that is an app that looks broken.
const paywalled = computed(() => members.subscriptionExpired)

// Not belonging to a company. `hasOrganization` answers true until the API has
// spoken, so no cold load flashes this at a member.
const needsActivation = computed(() => !isEscapeHatch.value && !members.hasOrganization)

// Belonging, but not granted this section. Used to be no blur at all — a
// narrowed manager saw the page and watched every request on it answer 403.
//
// `meta.modules` (plural) is for a page built from two sections at once:
// «Сводка» shows «Отчёты» money beside «Мониторинг» demand, and a manager
// granted one of the two must not be shown the other one's figures here. Every
// key listed has to be granted, which is what its API asks for as well.
const requiredModules = computed(
  () => route.meta.modules ?? (route.meta.module ? [route.meta.module] : []),
)

const blockedByModule = computed(
  () =>
    !isEscapeHatch.value &&
    requiredModules.value.length > 0 &&
    members.hasOrganization &&
    !requiredModules.value.every((key) => members.canReach(key)),
)

const allowed = computed(() => !paywalled.value && !needsActivation.value && !blockedByModule.value)

/** «до 9 сентября 2026 г.» — the date the term ran out, when we know it. */
const lapsedOn = computed(() => {
  const iso = members.subscription?.expires_at
  if (!iso) return ''
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime())
    ? ''
    : parsed.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
})
</script>

<template>
  <div class="relative">
    <!-- `inert` is the load-bearing half: without it the blurred page still
         takes Tab focus, so a keyboard user lands in inputs they cannot see. -->
    <div :class="allowed ? '' : 'gate-blurred'" :inert="!allowed">
      <slot />
    </div>

    <div v-if="!allowed" class="gate-overlay">
      <!-- The paywall. No form: renewal is a manual transfer between two
           humans, so the only honest next step is «напишите нам». An owner is
           told to renew; a manager is told who to ask, because they cannot. -->
      <section v-if="paywalled" class="gate-card">
        <h2 class="text-h2 font-bold tracking-tight text-primary">Подписка истекла</h2>
        <p v-if="lapsedOn" class="mt-xs text-tiny font-medium text-muted">
          Срок действия закончился {{ lapsedOn }}, льготные дни израсходованы.
        </p>
        <p class="mt-sm text-tiny font-medium text-muted">
          <template v-if="members.isOwner">
            Доступ к сервису закрыт до продления. Напишите нам, чтобы продлить подписку — данные
            компании сохранены и вернутся сразу после оплаты.
          </template>
          <template v-else>
            Доступ к сервису закрыт: подписка компании не продлена. Обратитесь к владельцу компании
            — продлить её может только он.
          </template>
        </p>
      </section>

      <!-- Narrowed manager: the section exists, they simply may not see it. No
           form here, because nothing they can type changes it — only their
           owner can. -->
      <section v-else-if="blockedByModule" class="gate-card">
        <h2 class="text-h2 font-bold tracking-tight text-primary">Раздел недоступен</h2>
        <p class="mt-xs text-tiny font-medium text-muted">
          У вас нет доступа к этому разделу. Его открывает владелец компании.
        </p>
      </section>

      <section v-else class="gate-card">
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
