<script setup>
/**
 * The left rail: who you are, where you are, and the four sections.
 *
 * This is the half of the redesign that answers «мы не используем ширину».
 * The old page stacked everything in a 672px column down the middle of a
 * 1280px canvas; the rail takes the space to the left and turns it into
 * standing context — identity, company, term — that used to be one «Email: …»
 * row and nothing else.
 *
 * The links are ANCHORS, not routes. Splitting a page this small into four
 * routes would buy navigation and sell four near-empty screens.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { currentSectionId } from '@/core/utils/sectionSpy'

const props = defineProps({
  email: { type: String, default: '' },
  roleLabel: { type: String, default: '' },
  orgName: { type: String, default: '' },
  /** `{ state, expires_at }` from /v1/organizations/me, or null. */
  subscription: { type: Object, default: null },
  /** @type {Array<{id: string, label: string, count: [String, Number]}>} */
  sections: { type: Array, required: true },
})

const active = ref(props.sections[0]?.id ?? null)

/** Until this moment, ignore the scroll: a click has already decided. */
let clickHoldsUntil = 0
const CLICK_HOLD_MS = 900
let frame = 0

const SUBSCRIPTION_TONE = {
  active: { label: 'Подписка активна', tone: 'is-ok' },
  grace: { label: 'Подписка истекает', tone: 'is-warn' },
  expired: { label: 'Подписка закончилась', tone: 'is-bad' },
}

const initial = ref('')

function syncToScroll() {
  if (Date.now() < clickHoldsUntil) return
  active.value = currentSectionId({
    sections: props.sections
      .map((section) => {
        const el = document.getElementById(section.id)
        return el ? { id: section.id, top: el.getBoundingClientRect().top } : null
      })
      .filter(Boolean),
    viewportHeight: window.innerHeight,
    scrollY: window.scrollY,
    // Without this the last section can never light: it is short enough to sit
    // below the reading line with nowhere left to scroll.
    pageHeight: document.documentElement.scrollHeight,
  })
}

function onScroll() {
  if (frame) return
  frame = requestAnimationFrame(() => {
    frame = 0
    syncToScroll()
  })
}

function go(id) {
  active.value = id
  clickHoldsUntil = Date.now() + CLICK_HOLD_MS
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function expiryText(iso) {
  return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: 'long' })
}

onMounted(() => {
  initial.value = (props.email || '?').trim().charAt(0).toUpperCase()
  window.addEventListener('scroll', onScroll, { passive: true })
  syncToScroll()
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', onScroll)
  if (frame) cancelAnimationFrame(frame)
})
</script>

<template>
  <div class="lp-rail">
    <div class="lp-rail__id">
      <span class="lp-rail__avatar" aria-hidden="true">{{ initial }}</span>
      <span class="min-w-0">
        <span class="lp-rail__email" :title="email">{{ email || '—' }}</span>
        <span class="lp-rail__org">{{ orgName || 'Без компании' }}</span>
      </span>
    </div>

    <span v-if="roleLabel" class="lp-rail__role">{{ roleLabel }}</span>

    <nav class="lp-rail__nav" aria-label="Разделы профиля">
      <button
        v-for="section in sections"
        :key="section.id"
        type="button"
        class="lp-rail__link"
        :class="active === section.id ? 'is-active' : ''"
        @click="go(section.id)"
      >
        <span class="truncate">{{ section.label }}</span>
        <span v-if="section.count !== undefined && section.count !== null" class="lp-rail__count">
          {{ section.count }}
        </span>
      </button>
    </nav>

    <div
      v-if="subscription"
      class="lp-rail__sub"
      :class="SUBSCRIPTION_TONE[subscription.state]?.tone"
    >
      <span class="lp-rail__sub-label">
        {{ SUBSCRIPTION_TONE[subscription.state]?.label ?? 'Подписка' }}
      </span>
      <span class="lp-rail__sub-date">до {{ expiryText(subscription.expires_at) }}</span>
    </div>
  </div>
</template>

<style scoped>
.lp-rail {
  @apply flex flex-col gap-md;
}

.lp-rail__id {
  @apply flex items-center gap-sm;
}

.lp-rail__avatar {
  @apply grid h-10 w-10 shrink-0 place-items-center rounded-full text-base font-bold;
  background: var(--ui-action-soft);
  color: var(--ui-action);
}

.lp-rail__email {
  @apply block truncate text-base font-semibold text-primary;
}

.lp-rail__org {
  @apply block truncate text-tiny font-medium text-muted;
}

.lp-rail__role {
  @apply w-fit rounded-btn px-sm py-xs text-tiny font-semibold;
  background: var(--ui-sunk);
  color: var(--ui-muted);
}

.lp-rail__nav {
  @apply flex flex-col gap-xs;
}

.lp-rail__link {
  @apply flex items-center justify-between gap-sm rounded-input px-md py-sm text-base font-medium transition;
  color: var(--ui-muted);
}

.lp-rail__link:hover {
  background: var(--ui-sunk);
  color: var(--ui-ink);
}

.lp-rail__link.is-active {
  background: var(--ui-action-soft);
  color: var(--ui-action);
  font-weight: 600;
}

.lp-rail__count {
  @apply shrink-0 text-tiny font-semibold tabular-nums;
  color: var(--ui-faint);
}

.lp-rail__link.is-active .lp-rail__count {
  color: var(--ui-action);
}

.lp-rail__sub {
  @apply flex flex-col gap-xs rounded-card px-md py-sm;
  background: var(--ui-sunk);
}

.lp-rail__sub-label {
  @apply text-tiny font-semibold;
  color: var(--ui-muted);
}

.lp-rail__sub-date {
  @apply text-base font-semibold text-primary;
}

.lp-rail__sub.is-warn .lp-rail__sub-label {
  color: var(--ui-warn);
}

.lp-rail__sub.is-bad .lp-rail__sub-label {
  color: var(--ui-neg);
}

/* On a phone the rail is a horizontal strip above the content: a 240px column
   has nowhere to go at 390px, and a sticky one would eat a third of the screen. */
@media (max-width: 1023px) {
  .lp-rail__nav {
    @apply -mx-md flex-row overflow-x-auto px-md;
    scrollbar-width: none;
  }

  .lp-rail__nav::-webkit-scrollbar {
    display: none;
  }

  .lp-rail__link {
    @apply shrink-0;
  }
}
</style>
