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

defineProps({
  workspaces: { type: Array, default: () => [] },
  currentId: { type: String, default: null },
  /** workspace id -> { configured: string[], is_primary: boolean } | undefined */
  tokenStatuses: { type: Object, default: () => ({}) },
  canManage: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['create', 'select', 'tokens', 'remove'])

const newName = ref('')
const confirming = ref(null)

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

function onRemove(id) {
  if (confirming.value !== id) {
    confirming.value = id
    setTimeout(() => {
      if (confirming.value === id) confirming.value = null
    }, 4000)
    return
  }
  confirming.value = null
  emit('remove', id)
}
</script>

<template>
  <div class="lp-panel">
    <header class="lp-panel__head">
      <div class="min-w-0">
        <h2 class="lp-panel__title">Кабинеты</h2>
        <p class="lp-panel__note">
          Все данные показываются в рамках выбранного кабинета. Токены WB хранятся в зашифрованном
          виде и никогда не показываются повторно.
        </p>
      </div>

      <form v-if="canManage" class="lp-panel__form" @submit.prevent="onCreate">
        <input
          v-model="newName"
          type="text"
          placeholder="Название нового"
          class="lp-input"
          aria-label="Название нового кабинета"
        />
        <button type="submit" class="lp-btn lp-btn--primary" :disabled="busy || !newName.trim()">
          Создать
        </button>
      </form>
    </header>

    <p v-if="!workspaces.length" class="lp-empty">Пока нет ни одного кабинета.</p>

    <div v-else class="lp-grid" role="table">
      <div class="lp-grid__head" role="row">
        <span role="columnheader">Название</span>
        <span role="columnheader">Токены WB</span>
        <span role="columnheader">Создано</span>
        <span role="columnheader" class="sr-only">Действия</span>
      </div>

      <div v-for="ws in workspaces" :key="ws.id" class="lp-grid__row" role="row">
        <span class="lp-cell lp-cell--who" role="cell">
          <span class="lp-who__mail" :title="ws.name">{{ ws.name }}</span>
          <span class="lp-cell--chips">
            <!-- «Активно» said nothing: every кабинет in the list is active.
                 What this marks is the one whose data the rest of the app is
                 currently showing — so it says that, and pairs with the
                 «Выбрать» on every other row. -->
            <span v-if="ws.id === currentId" class="lp-pill is-on">Выбран</span>
            <span v-if="ws.is_primary" class="lp-pill is-soft">основное</span>
          </span>
        </span>

        <span class="lp-cell" role="cell">
          <template v-if="!canManage">
            <span class="lp-who__meta">—</span>
          </template>
          <template v-else-if="tokenSummary(ws, tokenStatuses)">
            <span
              class="lp-pill"
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
          <span v-else class="lp-who__meta">…</span>
        </span>

        <span class="lp-cell lp-who__meta" role="cell">
          {{ new Date(ws.created_at).toLocaleDateString('ru-RU') }}
        </span>

        <span class="lp-cell lp-cell--act" role="cell">
          <button
            v-if="ws.id !== currentId"
            type="button"
            class="lp-btn"
            @click="emit('select', ws.id)"
          >
            Выбрать
          </button>
          <template v-if="canManage">
            <button type="button" class="lp-btn" @click="emit('tokens', ws)">Токены</button>
            <button
              type="button"
              class="lp-btn lp-btn--danger"
              :class="confirming === ws.id ? 'is-armed' : ''"
              :disabled="busy"
              @click="onRemove(ws.id)"
            >
              {{ confirming === ws.id ? 'Точно?' : 'Удалить' }}
            </button>
          </template>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lp-grid__head,
.lp-grid__row {
  /* Fixed tracks for the same reason as the team grid: the header is its own
     grid, so an `auto` column would not agree with the rows. */
  grid-template-columns: minmax(12rem, 2fr) 9rem 7rem 13rem;
}

@media (max-width: 1023px) {
  .lp-grid__head {
    @apply hidden;
  }

  .lp-grid__row {
    @apply grid-cols-1 gap-sm;
  }

  .lp-cell--act {
    @apply justify-start;
  }
}
</style>
