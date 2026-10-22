<script setup>
/**
 * «Кабинеты» — the list, and what state each one's WB credentials are in.
 *
 * The old panel hid the credentials behind a per-row accordion, which meant
 * you could not see from the list which workspace was actually wired up — and
 * for the primary workspace the accordion contained THIRTEEN password fields
 * inside a list item. Here the row reports the count and the drawer holds the
 * form.
 */
import { ref } from 'vue'

import { confirmLabel, useConfirmClick } from '@/core/utils/confirmClick'
import { formatMoscowDate } from '@/core/utils/moscow'

defineProps({
  workspaces: { type: Array, default: () => [] },
  currentId: { type: String, default: null },
  /** workspace id -> { configured: string[], is_primary: boolean } | undefined */
  tokenStatuses: { type: Object, default: () => ({}) },
  canManage: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
  /** A create is in flight — the button says so; `busy` covers every action. */
  creating: { type: Boolean, default: false },
})

const emit = defineEmits(['create', 'select', 'tokens', 'remove'])

const newName = ref('')

/** The primary workspace takes a token per WB category; the rest take one. */
function tokenSummary(ws, statuses) {
  const status = statuses[ws.id]
  if (!status) return null
  const total = ws.is_primary ? 13 : 1
  return { set: status.configured.length, total }
}

function onCreate() {
  const name = newName.value.trim()
  if (!name) return
  emit('create', name)
  newName.value = ''
}

const removal = useConfirmClick()
</script>

<template>
  <div class="pf-panel">
    <header class="pf-panel__head">
      <div class="min-w-0">
        <h2 class="pf-panel__title">Кабинеты</h2>
      </div>

      <form v-if="canManage" class="pf-panel__form" @submit.prevent="onCreate">
        <input
          v-model="newName"
          type="text"
          placeholder="Название нового"
          class="ui-input w-full"
          aria-label="Название нового кабинета"
        />
        <button type="submit" class="ui-btn ui-btn--primary" :disabled="busy || !newName.trim()">
          {{ creating ? 'Создаём…' : 'Создать' }}
        </button>
      </form>
    </header>

    <p v-if="!workspaces.length" class="pf-empty">Пока нет ни одного кабинета.</p>

    <div v-else class="pf-grid" :class="canManage ? '' : 'is-readonly'" role="table">
      <div class="pf-grid__head" role="row">
        <span role="columnheader">Название</span>
        <!-- A manager cannot set a token, so a column of «—» for them is a
             column that says nothing. -->
        <span v-if="canManage" role="columnheader">Токены WB</span>
        <span role="columnheader">Создан</span>
        <span role="columnheader" class="sr-only">Действия</span>
      </div>

      <div v-for="ws in workspaces" :key="ws.id" class="pf-grid__row" role="row">
        <span class="pf-cell pf-cell--who" role="cell">
          <span class="pf-who__mail" :title="ws.name">{{ ws.name }}</span>
          <span class="pf-cell--chips">
            <!-- «Активно» said nothing: every workspace in the list is active.
                 What this marks is the one whose data the rest of the app is
                 currently showing — so it says that, and pairs with the
                 «Выбрать» on every other row. -->
            <span v-if="ws.id === currentId" class="ui-badge is-on">Выбран</span>
            <span v-if="ws.is_primary" class="ui-badge is-soft">основной</span>
          </span>
        </span>

        <span v-if="canManage" class="pf-cell" role="cell">
          <template v-if="tokenSummary(ws, tokenStatuses)">
            <span
              class="ui-badge"
              :class="
                tokenSummary(ws, tokenStatuses).set === 0
                  ? 'is-bad'
                  : tokenSummary(ws, tokenStatuses).set < tokenSummary(ws, tokenStatuses).total
                    ? 'is-warn'
                    : 'is-ok'
              "
            >
              {{ tokenSummary(ws, tokenStatuses).set }} из
              {{ tokenSummary(ws, tokenStatuses).total }}
            </span>
          </template>
          <span v-else class="pf-who__meta">…</span>
        </span>

        <span class="pf-cell pf-who__meta" role="cell">
          {{ formatMoscowDate(ws.created_at) }}
        </span>

        <span class="pf-cell pf-cell--act" role="cell">
          <button
            v-if="ws.id !== currentId"
            type="button"
            class="ui-btn ui-btn--ghost ui-btn--sm"
            @click="emit('select', ws.id)"
          >
            Выбрать
          </button>
          <template v-if="canManage">
            <button
              type="button"
              class="ui-btn ui-btn--ghost ui-btn--sm"
              @click="emit('tokens', ws)"
            >
              Токены
            </button>
            <button
              type="button"
              class="ui-btn ui-btn--danger ui-btn--sm"
              :class="removal.isArmed(ws.id) ? 'is-armed' : ''"
              :disabled="busy"
              @click="removal.press(ws.id, () => emit('remove', ws.id))"
            >
              {{ removal.isArmed(ws.id) ? confirmLabel('Delete') : 'Delete' }}
            </button>
          </template>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pf-grid__head,
.pf-grid__row {
  /* Fixed tracks for the same reason as the team grid: the header is its own
     grid, so an `auto` column would not agree with the rows. */
  grid-template-columns: minmax(12rem, 2fr) 9rem 7rem 13rem;
}

/* One column fewer, and the name takes the room it leaves. */
.pf-grid.is-readonly .pf-grid__head,
.pf-grid.is-readonly .pf-grid__row {
  grid-template-columns: minmax(12rem, 2fr) 7rem 13rem;
}

@media (max-width: 1023px) {
  .pf-grid__head {
    @apply hidden;
  }

  .pf-grid__row {
    @apply grid-cols-1 gap-sm;
  }

  .pf-cell--act {
    @apply justify-start;
  }
}
</style>
