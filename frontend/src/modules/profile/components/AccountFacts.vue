<script setup>
/**
 * The four facts about this account, as a line rather than as a dashboard.
 *
 * They were stat tiles, and tiles were the wrong instrument twice over: a tile
 * is for a number that MOVES and that you came to read, and none of these is —
 * a term that ends in ten years and a count of two workspaces are standing facts,
 * checked once and then ignored. Four boxes for four constants is a dashboard
 * pretending something is happening.
 *
 * So: label above value, four of them on one rule, the way GitHub and Slack
 * put account facts under an identity block. No borders between the columns —
 * the alignment does that work, and dividers on a four-item row read as a table
 * somebody forgot to finish.
 *
 * The plan LIMITS are deliberately absent. «2 / 5 кабинетов» invites the
 * question "what happens at 5?" on a screen that cannot answer it, and the API
 * refuses the sixth one with a message that can.
 *
 * The subscription is absent for a different reason: it moved to the rail,
 * where it is visible from all three pages instead of only from this one.
 */
defineProps({
  roleLabel: { type: String, default: '—' },
  workspaces: { type: Number, default: 0 },
  /** `null` for an account that may not see the roster. */
  managers: { type: Number, default: null },
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
</script>

<template>
  <dl class="pf-facts">
    <div class="pf-fact">
      <dt class="pf-fact__label">Доступ</dt>
      <dd class="pf-fact__value">{{ roleLabel }}</dd>
    </div>

    <div class="pf-fact">
      <dt class="pf-fact__label">Кабинеты</dt>
      <dd class="pf-fact__value">
        {{ workspaces }}
        <span class="pf-fact__aside">
          {{ plural(workspaces, ['подключён', 'подключено', 'подключено']) }}
        </span>
      </dd>
    </div>

    <div v-if="managers !== null" class="pf-fact">
      <dt class="pf-fact__label">Команда</dt>
      <dd class="pf-fact__value">
        {{ managers }}
        <span class="pf-fact__aside">
          {{ plural(managers, ['менеджер', 'менеджера', 'менеджеров']) }}
        </span>
      </dd>
    </div>
  </dl>
</template>

<style scoped>
.pf-facts {
  @apply flex flex-wrap gap-x-xl gap-y-md;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--ui-hairline);
}

.pf-fact {
  @apply flex min-w-0 flex-col gap-xs;
}

.pf-fact__label {
  @apply text-tiny font-semibold uppercase tracking-wide;
  color: var(--ui-faint);
}

.pf-fact__value {
  @apply truncate text-base font-semibold text-primary;
}

/* The quiet half of the value — the unit, the remainder, the count's noun. */
.pf-fact__aside {
  @apply font-medium;
  color: var(--ui-muted);
}
</style>
