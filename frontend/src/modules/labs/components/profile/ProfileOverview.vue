<script setup>
/**
 * «Обзор» — the facts the old page never showed.
 *
 * Everything here already came back from `/v1/organizations/me` and
 * `/v1/workspaces` on the old page too; it rendered one of them (the email)
 * and threw the rest away. A seller could not tell from their profile how long
 * their term runs, how many workspaces their plan allows, or which sections
 * they are actually paying for.
 *
 * Quota tiles draw a meter only when the plan HAS a limit: `max_*` is null for
 * unlimited, and a full bar would read as "you are out".
 */
import { computed } from 'vue'

import { moduleLabel } from '@/modules/labs/components/profile/grantModules'

const props = defineProps({
  orgName: { type: String, default: '' },
  isPrimaryOrg: { type: Boolean, default: false },
  roleLabel: { type: String, default: '—' },
  workspaces: { type: Number, default: 0 },
  maxWorkspaces: { type: Number, default: null },
  managers: { type: Number, default: null },
  maxManagers: { type: Number, default: null },
  modules: { type: Array, default: () => [] },
  subscription: { type: Object, default: null },
})

/** Days left on the term, floored at 0 — a lapsed term says «истекла». */
const daysLeft = computed(() => {
  if (!props.subscription) return null
  const ms = new Date(props.subscription.expires_at).getTime() - Date.now()
  return Math.max(0, Math.ceil(ms / 86400000))
})

function ratio(used, max) {
  if (!max) return null
  return Math.min(100, Math.round((used / max) * 100))
}

const workspaceRatio = computed(() => ratio(props.workspaces, props.maxWorkspaces))
const managerRatio = computed(() => ratio(props.managers ?? 0, props.maxManagers))

/** «5 дней» / «2 дня» / «1 день» — the count decides the ending. */
function plural(n, forms) {
  const mod100 = n % 100
  if (mod100 >= 11 && mod100 <= 14) return forms[2]
  const mod10 = n % 10
  if (mod10 === 1) return forms[0]
  if (mod10 >= 2 && mod10 <= 4) return forms[1]
  return forms[2]
}
</script>

<template>
  <div class="lp-tiles">
    <article class="lp-tile">
      <span class="lp-tile__label">Компания</span>
      <span class="lp-tile__value" :title="orgName">{{ orgName || 'Не привязана' }}</span>
      <span v-if="isPrimaryOrg" class="lp-tile__note">основная организация</span>
      <span v-else class="lp-tile__note">роль: {{ roleLabel }}</span>
    </article>

    <article class="lp-tile">
      <span class="lp-tile__label">Подписка</span>
      <span v-if="daysLeft === null" class="lp-tile__value">—</span>
      <span v-else-if="daysLeft === 0" class="lp-tile__value lp-tile__value--bad">истекла</span>
      <span v-else class="lp-tile__value">
        {{ daysLeft }}
        <small>{{ plural(daysLeft, ['день', 'дня', 'дней']) }}</small>
      </span>
      <span v-if="subscription" class="lp-tile__note">
        до {{ new Date(subscription.expires_at).toLocaleDateString('ru-RU') }}
      </span>
    </article>

    <article class="lp-tile">
      <span class="lp-tile__label">Кабинеты</span>
      <span class="lp-tile__value">
        {{ workspaces }}<small v-if="maxWorkspaces"> / {{ maxWorkspaces }}</small>
      </span>
      <span v-if="workspaceRatio !== null" class="lp-meter">
        <span class="lp-meter__fill" :style="{ width: `${workspaceRatio}%` }" />
      </span>
      <span v-else class="lp-tile__note">без ограничения</span>
    </article>

    <article v-if="managers !== null" class="lp-tile">
      <span class="lp-tile__label">Менеджеры</span>
      <span class="lp-tile__value">
        {{ managers }}<small v-if="maxManagers"> / {{ maxManagers }}</small>
      </span>
      <span v-if="managerRatio !== null" class="lp-meter">
        <span class="lp-meter__fill" :style="{ width: `${managerRatio}%` }" />
      </span>
      <span v-else class="lp-tile__note">без ограничения</span>
    </article>

    <article class="lp-tile">
      <span class="lp-tile__label">Доступные разделы</span>
      <span v-if="modules.length" class="lp-tile__chips">
        <span v-for="key in modules" :key="key" class="lp-chip">{{ moduleLabel(key) }}</span>
      </span>
      <span v-else class="lp-tile__note">пока ни одного</span>
    </article>
  </div>
</template>

<style scoped>
.lp-tiles {
  @apply grid gap-md;
  grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
}

.lp-tile {
  @apply flex flex-col gap-xs rounded-card px-md py-md;
  background: var(--ui-surface);
  box-shadow: var(--ui-sh-xs);
}

.lp-tile__label {
  @apply text-tiny font-semibold uppercase tracking-wide;
  color: var(--ui-faint);
}

.lp-tile__value {
  @apply truncate text-h2 font-bold text-primary;
}

.lp-tile__value--bad {
  color: var(--ui-neg);
}

.lp-tile__value small {
  @apply text-base font-medium;
  color: var(--ui-muted);
}

.lp-tile__note {
  @apply truncate text-tiny font-medium;
  color: var(--ui-muted);
}

.lp-tile__chips {
  @apply flex flex-wrap gap-xs;
}

.lp-chip {
  @apply rounded-btn px-sm py-xs text-tiny font-semibold;
  background: var(--ui-action-soft);
  color: var(--ui-action);
}

.lp-meter {
  @apply block h-1 w-full overflow-hidden rounded-btn;
  background: var(--ui-sunk);
}

.lp-meter__fill {
  @apply block h-full rounded-btn;
  background: var(--ui-action);
}
</style>
