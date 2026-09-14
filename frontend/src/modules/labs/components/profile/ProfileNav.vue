<script setup>
/**
 * The settings rail: who you are, and the three places settings live.
 *
 * **Why it does not read as a white slab.** A nav painted `--ui-surface` is the
 * same material as every card beside it, so on a canvas this light the two
 * merge and the rail stops reading as chrome. Instead it is a GROOVE: the rail
 * is the sunk tone with a 1px inset ring, and the active item is a white pill
 * with the card shadow, so the selected page looks like it has risen out of the
 * rail towards the content it belongs to. One material, two depths — no new
 * colour, no glass in a place that does not float.
 *
 * Routes, not anchors, this time. The anchor version was right while the page
 * was «чуть больше экрана высоты»; with a real security section it is three
 * screens, and three screens under one scrollbar is a page you scroll past
 * rather than navigate.
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

const props = defineProps({
  email: { type: String, default: '' },
  roleLabel: { type: String, default: '' },
  /** @type {Array<{name: string, label: string}>} */
  sections: { type: Array, required: true },
  /** `{ state, expires_at }` from /v1/organizations/me, or null. */
  subscription: { type: Object, default: null },
})

const SUBSCRIPTION_TONE = {
  active: 'is-ok',
  grace: 'is-warn',
  expired: 'is-bad',
}

/** «до 14 сентября» — no year: a term that ends this decade does not need one. */
const until = computed(() =>
  props.subscription
    ? new Date(props.subscription.expires_at).toLocaleDateString('ru-RU', {
        day: 'numeric',
        month: 'long',
      })
    : '',
)

/** Days left, floored at 0 — a lapsed term says so instead of counting down. */
const daysLeft = computed(() => {
  if (!props.subscription) return null
  const ms = new Date(props.subscription.expires_at).getTime() - Date.now()
  return Math.max(0, Math.ceil(ms / 86400000))
})

/** «5 дней» / «2 дня» / «1 день» — the count decides the ending. */
function plural(n, forms) {
  const mod100 = n % 100
  if (mod100 >= 11 && mod100 <= 14) return forms[2]
  const mod10 = n % 10
  if (mod10 === 1) return forms[0]
  if (mod10 >= 2 && mod10 <= 4) return forms[1]
  return forms[2]
}

/** First letter of the address, as a stand-in for an avatar nobody uploads. */
function initialOf(email) {
  return (email || '?').trim().charAt(0).toUpperCase()
}
</script>

<template>
  <nav class="lp-nav" aria-label="Настройки">
    <div class="lp-nav__id">
      <span class="lp-nav__avatar" aria-hidden="true">{{ initialOf(email) }}</span>
      <span class="min-w-0">
        <span class="lp-nav__email" :title="email">{{ email || '—' }}</span>
        <span class="lp-nav__role">{{ roleLabel || '—' }}</span>
      </span>
    </div>

    <ul class="lp-nav__list">
      <li v-for="section in sections" :key="section.name">
        <RouterLink
          class="lp-nav__link"
          active-class="is-active"
          :to="{ name: section.name }"
          exact-active-class="is-active"
        >
          {{ section.label }}
        </RouterLink>
      </li>
    </ul>

    <!-- The term, in the rail rather than on «Общие». It belongs to the account
         rather than to any one page, and it is the one fact here worth seeing
         from all three. -->
    <div v-if="subscription" class="lp-nav__sub" :class="SUBSCRIPTION_TONE[subscription.state]">
      <span class="lp-nav__sub-date">До {{ until }}</span>
      <span v-if="daysLeft !== null" class="lp-nav__sub-left">
        {{
          daysLeft === 0
            ? 'подписка истекла'
            : `осталось ${daysLeft} ${plural(daysLeft, ['день', 'дня', 'дней'])}`
        }}
      </span>
    </div>
  </nav>
</template>

<style scoped>
.lp-nav {
  @apply flex flex-col gap-md rounded-card p-sm;
  /* The groove: sunk tone, and an inset ring rather than a border — a border
     would draw a line around a thing that is meant to read as an absence. */
  background: var(--ui-sunk);
  box-shadow: inset 0 0 0 1px rgba(18, 18, 26, 0.05);
}

.lp-nav__id {
  @apply flex items-center gap-sm px-sm pt-sm;
}

.lp-nav__avatar {
  @apply grid h-9 w-9 shrink-0 place-items-center rounded-full text-base font-bold;
  background: var(--ui-action);
  color: #fff;
}

.lp-nav__email {
  @apply block truncate text-base font-semibold text-primary;
}

.lp-nav__role {
  @apply block truncate text-tiny font-medium;
  color: var(--ui-muted);
}

.lp-nav__list {
  @apply flex flex-col gap-xs;
}

.lp-nav__link {
  @apply block rounded-input px-md py-sm text-base font-semibold transition;
  color: var(--ui-muted);
}

.lp-nav__link:hover {
  background: rgba(255, 255, 255, 0.6);
  color: var(--ui-ink);
}

/* Risen out of the groove: the one white surface inside it, carrying the same
   shadow the content cards do, so it reads as the same material as the page. */
.lp-nav__link.is-active {
  background: var(--ui-surface);
  box-shadow: var(--ui-sh-xs);
  color: var(--ui-ink);
}

.lp-nav__sub {
  @apply flex flex-col gap-0 px-md pb-sm;
}

.lp-nav__sub-date {
  @apply text-base font-semibold text-primary;
}

.lp-nav__sub-left {
  @apply text-tiny font-medium;
  color: var(--ui-muted);
}

.lp-nav__sub.is-warn .lp-nav__sub-date {
  color: var(--ui-warn);
}

.lp-nav__sub.is-bad .lp-nav__sub-date {
  color: var(--ui-neg);
}

/* On a phone the rail becomes a strip: a 260px column has nowhere to go at
   390px, and the groove works just as well lying down. */
@media (max-width: 767px) {
  .lp-nav__list {
    @apply -mx-sm flex-row overflow-x-auto px-sm;
    scrollbar-width: none;
  }

  .lp-nav__list::-webkit-scrollbar {
    display: none;
  }

  .lp-nav__link {
    @apply shrink-0;
  }
}
</style>
