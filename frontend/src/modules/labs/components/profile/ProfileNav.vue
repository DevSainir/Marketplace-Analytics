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
import { RouterLink } from 'vue-router'

defineProps({
  email: { type: String, default: '' },
  roleLabel: { type: String, default: '' },
  /** @type {Array<{name: string, label: string, hint: string}>} */
  sections: { type: Array, required: true },
})

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
          <span class="lp-nav__label">{{ section.label }}</span>
          <span class="lp-nav__hint">{{ section.hint }}</span>
        </RouterLink>
      </li>
    </ul>
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
  @apply flex flex-col gap-0 rounded-input px-md py-sm transition;
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

.lp-nav__label {
  @apply text-base font-semibold;
}

.lp-nav__hint {
  @apply truncate text-tiny font-medium;
  color: var(--ui-faint);
}

.lp-nav__link.is-active .lp-nav__hint {
  color: var(--ui-muted);
}

/* On a phone the rail becomes a strip: a 260px column has nowhere to go at
   390px, and the groove works just as well lying down. */
@media (max-width: 1023px) {
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

  .lp-nav__hint {
    @apply hidden;
  }
}
</style>
