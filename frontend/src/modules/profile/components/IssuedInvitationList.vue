<script setup>
/**
 * Every invitation this company has issued, and a way to withdraw one.
 *
 * It exists because pressing «Пригласить» twice produces TWO working links and
 * nothing supersedes anything: each is a separate row with its own token, live
 * until it is accepted, revoked, or expires. Without this list an owner who
 * clicked a few times had no way to know how many valid links were in the
 * world, let alone stop one — the API could list and revoke them the whole
 * time, and the SPA called neither.
 *
 * Tokens are never here. They exist once, in the response that created them.
 */
import { computed } from 'vue'

import { useMembersStore } from '@/modules/profile/membersStore'

const members = useMembersStore()

// `accepted` is deliberately absent: a link is reusable until it expires, so
// somebody having joined through it says nothing about whether it still works.
// How many came through is shown separately, as a count.
const STATUS = {
  pending: { label: 'Действует', tone: 'live' },
  revoked: { label: 'Отозвано', tone: 'muted' },
  expired: { label: 'Истекло', tone: 'muted' },
}

// Live ones first: they are the only rows that are still a way into the
// company, and therefore the only ones anybody needs to act on.
const rows = computed(() =>
  [...members.issued].sort(
    (a, b) => Number(b.status === 'pending') - Number(a.status === 'pending'),
  ),
)

const liveCount = computed(() => members.issued.filter((i) => i.status === 'pending').length)

function describe(status) {
  return STATUS[status] ?? { label: status, tone: 'muted' }
}

/**
 * Time as well as date: the default window is an hour, so a link that says only
 * «3 сент.» tells an owner nothing about whether it is still open.
 */
function shortDate(value) {
  return new Date(value).toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<template>
  <section v-if="rows.length" class="mt-lg">
    <h3 class="text-base font-semibold text-primary">Выданные приглашения</h3>
    <p class="mt-xs text-tiny font-medium text-muted">
      <template v-if="liveCount">
        Действующих ссылок: {{ liveCount }}. Пока ссылка действует, по ней может присоединиться
        любой, у кого она есть — отзовите те, что вы никому не отправляли.
      </template>
      <template v-else>Действующих ссылок нет.</template>
    </p>

    <ul class="mt-sm flex flex-col gap-xs">
      <li v-for="row in rows" :key="row.id" class="invite-row">
        <div class="min-w-0">
          <span class="block truncate text-base text-primary">
            {{ row.email ?? 'Ссылка без адреса' }}
          </span>
          <span class="text-tiny text-muted">
            до {{ shortDate(row.expires_at) }}
            <template v-if="row.accepted_count">
              · присоединились: {{ row.accepted_count }}</template
            >
          </span>
        </div>

        <div class="flex shrink-0 items-center gap-sm">
          <span class="badge" :class="`badge-${describe(row.status).tone}`">
            {{ describe(row.status).label }}
          </span>
          <!-- Offered on any live link, INCLUDING one somebody already used:
               that is the one an owner has evidence about, and revoking stops
               the next arrival. Removing whoever already joined is a separate
               act, on the members list. -->
          <button
            v-if="row.status === 'pending'"
            type="button"
            class="revoke"
            :disabled="members.saving === row.id"
            @click="members.revokeInvite(row.id)"
          >
            {{ members.saving === row.id ? 'Отзываем…' : 'Отозвать' }}
          </button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.invite-row {
  @apply flex items-center justify-between gap-md rounded-input border border-border-subtle px-md py-sm;
  background-color: var(--ui-canvas);
}

.badge {
  @apply rounded-btn px-sm py-xs text-tiny font-semibold whitespace-nowrap;
}

.badge-live {
  background-color: color-mix(in srgb, var(--ui-action) 12%, transparent);
  color: var(--ui-action);
}

.badge-done {
  background-color: color-mix(in srgb, var(--ui-pos) 12%, transparent);
  color: var(--ui-pos);
}

.badge-muted {
  background-color: color-mix(in srgb, var(--ui-muted) 12%, transparent);
  color: var(--ui-muted);
}

.revoke {
  @apply text-tiny font-semibold transition disabled:cursor-not-allowed disabled:opacity-60;
  color: var(--ui-neg);
}
</style>
