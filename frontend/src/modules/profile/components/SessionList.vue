<script setup>
/**
 * «Активные входы» — every browser this account is signed in on.
 *
 * Telegram's sessions screen is the reference, and the part worth copying is
 * the INFORMATION, not the chrome: what device, what app, where, when last
 * seen, and which one you are reading it on. The part not worth copying is its
 * modal-per-session — a row with its own «Завершить» is one press instead of
 * three, and there is nothing else to put in the modal.
 *
 * The User-Agent is parsed HERE and nowhere else. The server stores it raw on
 * purpose: parsing is presentation, it changes with every browser release, and
 * a string this function does not recognise must show as «Неизвестное
 * устройство» rather than as a confident guess about a device somebody is
 * deciding whether to trust.
 */
import { computed } from 'vue'

import DataState from '@/core/components/DataState.vue'
import { confirmLabel, useConfirmClick } from '@/core/utils/confirmClick'

const props = defineProps({
  /** @type {Array<object>} rows from GET /v1/auth/sessions */
  sessions: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  /** Why the list could not be read; empty when it was. */
  error: { type: String, default: '' },
  /** family_id currently being ended, or 'all'. */
  busy: { type: [String, null], default: null },
})

const emit = defineEmits(['end', 'end-others'])

/** Ending a session signs that device out: asked first (`confirmClick`). */
const ending = useConfirmClick()

const OS = [
  [/Windows NT 10/i, 'Windows'],
  [/Windows/i, 'Windows'],
  [/iPhone|iPad|iPod/i, 'iOS'],
  [/Mac OS X|Macintosh/i, 'macOS'],
  [/Android/i, 'Android'],
  [/CrOS/i, 'ChromeOS'],
  [/Linux/i, 'Linux'],
]

// Order matters: Edge and Opera both claim Chrome, and Chrome claims Safari.
const BROWSERS = [
  [/Edg\//i, 'Edge'],
  [/OPR\/|Opera/i, 'Opera'],
  [/YaBrowser/i, 'Яндекс.Браузер'],
  [/Firefox\//i, 'Firefox'],
  [/Chrome\//i, 'Chrome'],
  [/Safari\//i, 'Safari'],
]

function match(table, value) {
  return table.find(([pattern]) => pattern.test(value))?.[1] ?? null
}

/** «Chrome на macOS», or as much of it as the string actually supports. */
function describe(userAgent) {
  if (!userAgent) return { title: 'Неизвестное устройство', detail: 'Браузер не определился' }
  const os = match(OS, userAgent)
  const browser = match(BROWSERS, userAgent)
  if (!os && !browser) return { title: 'Неизвестное устройство', detail: userAgent.slice(0, 60) }
  return {
    title: browser && os ? `${browser} на ${os}` : (browser ?? os),
    detail: os && browser ? os : '',
  }
}

/** «только что» / «12 минут назад» / «вчера» / a date. */
function lastSeen(iso) {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 2) return 'сейчас'
  if (minutes < 60) return `${minutes} мин назад`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} ч назад`
  const days = Math.round(hours / 24)
  if (days === 1) return 'вчера'
  if (days < 7) return `${days} дн назад`
  return new Date(iso).toLocaleDateString('ru-RU')
}

const current = computed(() => props.sessions.find((session) => session.is_current) ?? null)
const others = computed(() => props.sessions.filter((session) => !session.is_current))
</script>

<template>
  <div class="pf-sessions">
    <DataState v-if="loading" kind="loading" />
    <DataState v-else-if="error" kind="error" :text="error" />

    <template v-else>
      <!-- The one you are reading this on, first and labelled — Telegram's one
           structural idea worth taking: you cannot decide about the others
           until you know which one is you. -->
      <section v-if="current" class="pf-sessions__group">
        <h3 class="pf-sessions__heading">Это устройство</h3>
        <article class="pf-session is-current">
          <span class="pf-session__main">
            <span class="pf-session__title">{{ describe(current.user_agent).title }}</span>
            <span class="pf-session__meta">
              {{ current.ip_address || 'адрес не записан' }} · вход
              {{ new Date(current.started_at).toLocaleDateString('ru-RU') }}
            </span>
          </span>
          <span class="pf-pill is-on">сейчас здесь</span>
        </article>
      </section>

      <section class="pf-sessions__group">
        <header class="pf-sessions__head">
          <h3 class="pf-sessions__heading">Другие устройства</h3>
          <button
            v-if="others.length"
            type="button"
            class="ui-btn ui-btn--danger ui-btn--sm"
            :class="ending.isArmed('all') ? 'is-armed' : ''"
            :disabled="busy === 'all'"
            @click="ending.press('all', () => emit('end-others'))"
          >
            {{
              busy === 'all'
                ? 'Завершаем…'
                : ending.isArmed('all')
                  ? confirmLabel('Завершить все')
                  : 'Завершить все'
            }}
          </button>
        </header>

        <p v-if="!others.length" class="pf-sessions__note">Больше нигде не выполнен вход.</p>

        <article v-for="session in others" :key="session.family_id" class="pf-session">
          <span class="pf-session__main">
            <span class="pf-session__title">{{ describe(session.user_agent).title }}</span>
            <span class="pf-session__meta">
              {{ session.ip_address || 'адрес не записан' }} · активность
              {{ lastSeen(session.last_seen_at) }}
            </span>
          </span>
          <button
            type="button"
            class="ui-btn ui-btn--danger ui-btn--sm"
            :class="ending.isArmed(session.family_id) ? 'is-armed' : ''"
            :disabled="busy === session.family_id"
            @click="ending.press(session.family_id, () => emit('end', session.family_id))"
          >
            {{
              busy === session.family_id
                ? 'Завершаем…'
                : ending.isArmed(session.family_id)
                  ? confirmLabel('Завершить')
                  : 'Завершить'
            }}
          </button>
        </article>
      </section>
    </template>
  </div>
</template>

<style scoped>
.pf-sessions {
  @apply flex flex-col gap-lg;
}

.pf-sessions__group {
  @apply flex flex-col gap-sm;
}

.pf-sessions__head {
  @apply flex items-center justify-between gap-md;
}

.pf-sessions__heading {
  @apply text-tiny font-semibold uppercase tracking-wide;
  color: var(--ui-faint);
}

.pf-sessions__note {
  @apply max-w-[52ch] text-tiny font-medium;
  color: var(--ui-muted);
}

.pf-session {
  @apply flex items-center justify-between gap-md rounded-card px-md py-sm;
  background: var(--ui-surface);
  box-shadow: var(--ui-sh-xs);
}

/* Tinted rather than white: it is context, not a row you are deciding about.
   The sunk grey was too close to the canvas to read as a separate thing at
   all, so it takes the action tint — the same one the «сейчас здесь» pill is
   made of, which is what ties the two together. */
.pf-session.is-current {
  background: var(--ui-action-soft);
  box-shadow: none;
}

.pf-session__main {
  @apply flex min-w-0 flex-col gap-xs;
}

.pf-session__title {
  @apply truncate text-base font-semibold text-primary;
}

.pf-session__meta {
  @apply truncate text-tiny font-medium;
  color: var(--ui-muted);
}

@media (max-width: 430px) {
  .pf-session {
    @apply flex-col items-start;
  }
}
</style>
