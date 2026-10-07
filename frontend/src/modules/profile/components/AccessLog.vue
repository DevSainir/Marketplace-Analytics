<script setup>
/**
 * «Журнал доступа» — who did what inside this company, newest first.
 *
 * The rows have existed since the audit trail was built and the endpoint since
 * it stopped being write-only, and nothing in the product ever rendered them.
 * That is the exact question an owner asks and cannot otherwise answer: «кто
 * убрал этого менеджера».
 *
 * **The line is a button.** A headline and a timestamp say that something
 * happened and nothing about what — «Изменён доступ» leaves out whose access,
 * and to what. Pressing it opens the same drawer the token and invite editors
 * use, with the whole entry in it. The row stays a row: the list is still
 * scannable, and the detail is one press away rather than five columns wide.
 *
 * **Paged, but only once there is something to page.** This is the one table
 * that only grows, so the endpoint bounds itself; below one page's worth the
 * controls are not drawn at all, and a company with six events never sees a
 * pager.
 *
 * The vocabulary and the per-event detail live in `auditEntry.js` — two
 * components need them, and the mapping is the part worth reading on its own.
 */
import { computed, ref } from 'vue'

import DataState from '@/core/components/DataState.vue'
import SidePanel from '@/modules/profile/components/SidePanel.vue'
import {
  REMOVING_EVENTS,
  detailRows,
  eventLabel,
  shortMoment,
} from '@/modules/profile/components/auditEntry'

const props = defineProps({
  /** @type {Array<object>} rows from GET /v1/organizations/audit-log */
  entries: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})

/** How many rows fit before the list stops being scannable. */
const PAGE_SIZE = 10

const page = ref(0)
const opened = ref(null)

const pageCount = computed(() => Math.ceil(props.entries.length / PAGE_SIZE))
const paged = computed(() =>
  props.entries.slice(page.value * PAGE_SIZE, page.value * PAGE_SIZE + PAGE_SIZE),
)

function step(delta) {
  page.value = Math.min(Math.max(page.value + delta, 0), pageCount.value - 1)
}
</script>

<template>
  <div class="pf-panel">
    <header class="pf-panel__head">
      <div class="min-w-0">
        <h2 class="pf-panel__title">Журнал доступа</h2>
        <p class="pf-panel__note">Что происходило с доступом в компании.</p>
      </div>
    </header>

    <DataState v-if="loading && !entries.length" kind="loading" />
    <DataState v-else-if="!entries.length" kind="empty" text="Пока ничего не происходило" />

    <template v-else>
      <ol class="pf-log">
        <li v-for="entry in paged" :key="entry.id" class="pf-log__row">
          <button type="button" class="pf-log__open" @click="opened = entry">
            <span class="pf-log__dot" :class="REMOVING_EVENTS.has(entry.event) ? 'is-bad' : ''" />
            <span class="pf-log__what">{{ eventLabel(entry.event) }}</span>
          </button>
          <span class="pf-log__who">{{ entry.actor_email || 'система' }}</span>
          <time class="pf-log__when" :datetime="entry.occurred_at">
            {{ shortMoment(entry.occurred_at) }}
          </time>
        </li>
      </ol>

      <nav v-if="pageCount > 1" class="pf-pager" aria-label="Страницы журнала">
        <button type="button" class="pf-btn" :disabled="page === 0" @click="step(-1)">Назад</button>
        <span class="pf-pager__count">{{ page + 1 }} из {{ pageCount }}</span>
        <button type="button" class="pf-btn" :disabled="page >= pageCount - 1" @click="step(1)">
          Дальше
        </button>
      </nav>
    </template>

    <SidePanel
      :open="Boolean(opened)"
      :title="opened ? eventLabel(opened.event) : ''"
      @close="opened = null"
    >
      <dl v-if="opened" class="pf-detail">
        <div v-for="row in detailRows(opened)" :key="row.label" class="pf-detail__row">
          <dt class="pf-detail__label">{{ row.label }}</dt>
          <dd class="pf-detail__value">{{ row.value }}</dd>
        </div>
      </dl>
    </SidePanel>
  </div>
</template>

<style scoped>
/* A rail rather than a table: these rows have one fact each and a table of
   one-fact rows is four columns of whitespace. The line down the left is what
   makes it read as a sequence. */
.pf-log {
  @apply relative flex flex-col gap-sm rounded-card px-lg py-md;
  background: var(--ui-surface);
  box-shadow: var(--ui-sh-xs);
}

.pf-log::before {
  content: '';
  @apply absolute bottom-md left-lg top-md w-px;
  background: var(--ui-hairline);
  transform: translateX(3px);
}

.pf-log__row {
  @apply relative grid items-baseline gap-x-sm;
  grid-template-columns: minmax(0, 1fr) minmax(0, auto) 5.5rem;
}

/* The dot and the headline are one target: a 7px dot on its own is not
   something anybody can hit. */
.pf-log__open {
  @apply relative -my-xs flex min-w-0 items-baseline gap-sm rounded-btn py-xs pl-lg pr-sm text-left transition;
}

.pf-log__open:hover {
  background: var(--ui-sunk);
}

.pf-log__dot {
  @apply absolute left-0 top-2 h-[7px] w-[7px] rounded-full;
  background: var(--ui-action);
  /* Punch through the rail so the line looks threaded, not crossed. */
  box-shadow: 0 0 0 3px var(--ui-surface);
}

.pf-log__open:hover .pf-log__dot {
  box-shadow: 0 0 0 3px var(--ui-sunk);
}

.pf-log__dot.is-bad {
  background: var(--ui-neg);
}

.pf-log__what {
  @apply truncate text-base font-medium text-primary;
}

.pf-log__who,
.pf-log__when {
  @apply truncate text-tiny font-medium tabular-nums;
  color: var(--ui-muted);
}

.pf-log__when {
  @apply text-right;
  color: var(--ui-faint);
}

.pf-pager {
  @apply flex items-center justify-end gap-sm;
}

.pf-pager__count {
  @apply text-tiny font-medium tabular-nums;
  color: var(--ui-muted);
}

.pf-detail {
  @apply flex flex-col gap-md;
}

.pf-detail__row {
  @apply flex flex-col gap-xs;
}

.pf-detail__label {
  @apply text-tiny font-semibold uppercase tracking-wide;
  color: var(--ui-faint);
}

.pf-detail__value {
  @apply break-words text-base font-medium text-primary;
}

@media (max-width: 640px) {
  .pf-log__row {
    grid-template-columns: minmax(0, 1fr) 5.5rem;
  }

  .pf-log__who {
    @apply col-span-2 truncate;
  }
}
</style>
