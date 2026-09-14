<script setup>
/**
 * «Журнал доступа» — who did what inside this company, newest first.
 *
 * The rows have existed since the audit trail was built and the endpoint since
 * it stopped being write-only, and nothing in the product ever rendered them.
 * That is the exact question an owner asks and cannot otherwise answer: «кто
 * убрал этого менеджера».
 *
 * The event vocabulary is translated HERE, not stored in Russian: the log is a
 * machine record first (an incident is read with grep, at 02:00, by us) and a
 * screen second. An event this map does not know is shown as its raw name
 * rather than hidden — an unrecognised entry is the one most worth seeing.
 */
defineProps({
  /** @type {Array<object>} rows from GET /v1/organizations/audit-log */
  entries: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})

const EVENTS = {
  ORG_ACTIVATED: 'Компания активирована',
  MEMBER_INVITED: 'Выдано приглашение',
  INVITATION_REVOKED: 'Приглашение отозвано',
  MEMBER_JOINED: 'Менеджер присоединился',
  MEMBER_REMOVED: 'Менеджер удалён из компании',
  MEMBER_ROLE_CHANGED: 'Изменена роль',
  MEMBER_ACCESS_CHANGED: 'Изменён доступ',
  WORKSPACE_CREATED: 'Создан кабинет',
  WORKSPACE_DELETED: 'Удалён кабинет',
  WB_TOKEN_ROTATED: 'Обновлён токен Wildberries',
  SESSIONS_REVOKED: 'Завершены сеансы',
  PASSWORD_CHANGED: 'Изменён пароль',
  ACTIVATION_CODE_ISSUED: 'Выдан ключ активации',
}

/** The events worth colouring — the ones that take something away. */
const REMOVING = new Set([
  'MEMBER_REMOVED',
  'INVITATION_REVOKED',
  'WORKSPACE_DELETED',
  'SESSIONS_REVOKED',
])

function when(iso) {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<template>
  <div class="lp-panel">
    <header class="lp-panel__head">
      <div class="min-w-0">
        <h2 class="lp-panel__title">Журнал доступа</h2>
        <p class="lp-panel__note">
          Что происходило с доступом в компании. Запись остаётся, даже если аккаунт потом удалили.
        </p>
      </div>
    </header>

    <p v-if="loading" class="lp-empty">Загружаем…</p>
    <p v-else-if="!entries.length" class="lp-empty">Пока ничего не происходило.</p>

    <ol v-else class="lp-log">
      <li v-for="entry in entries" :key="entry.id" class="lp-log__row">
        <span class="lp-log__dot" :class="REMOVING.has(entry.event) ? 'is-bad' : ''" />
        <span class="lp-log__what">
          {{ EVENTS[entry.event] ?? entry.event }}
        </span>
        <span class="lp-log__who">{{ entry.actor_email || 'система' }}</span>
        <time class="lp-log__when" :datetime="entry.occurred_at">{{
          when(entry.occurred_at)
        }}</time>
      </li>
    </ol>
  </div>
</template>

<style scoped>
/* A rail rather than a table: these rows have one fact each and a table of
   one-fact rows is four columns of whitespace. The line down the left is what
   makes it read as a sequence. */
.lp-log {
  @apply relative flex flex-col gap-sm rounded-card px-lg py-md;
  background: var(--ui-surface);
  box-shadow: var(--ui-sh-xs);
}

.lp-log::before {
  content: '';
  @apply absolute bottom-md left-lg top-md w-px;
  background: var(--ui-hairline);
  transform: translateX(3px);
}

.lp-log__row {
  @apply relative grid items-baseline gap-x-sm pl-lg;
  grid-template-columns: minmax(0, 1fr) minmax(0, auto) 5.5rem;
}

.lp-log__dot {
  @apply absolute left-0 top-1.5 h-[7px] w-[7px] rounded-full;
  background: var(--ui-action);
  /* Punch through the rail so the line looks threaded, not crossed. */
  box-shadow: 0 0 0 3px var(--ui-surface);
}

.lp-log__dot.is-bad {
  background: var(--ui-neg);
}

.lp-log__what {
  @apply truncate text-base font-medium text-primary;
}

.lp-log__who,
.lp-log__when {
  @apply truncate text-tiny font-medium tabular-nums;
  color: var(--ui-muted);
}

.lp-log__when {
  @apply text-right;
  color: var(--ui-faint);
}

@media (max-width: 640px) {
  .lp-log__row {
    grid-template-columns: minmax(0, 1fr) 5.5rem;
  }

  .lp-log__who {
    @apply col-span-2 truncate;
  }
}
</style>
