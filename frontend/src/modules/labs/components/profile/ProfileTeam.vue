<script setup>
/**
 * «Команда» — the members list as a control room.
 *
 * The old panel rendered the full grant editor inside every row: four controls
 * per manager, repeated. Five managers meant five copies of the same form and
 * a page whose height grew with the team. Here a row STATES the grant — level,
 * sections, since when — and editing it opens the drawer.
 *
 * Removal keeps the two-press confirm from the old panel: it cannot be undone
 * from this screen, and it is the thing that actually withdraws access from
 * somebody who has already joined.
 */
import { ref } from 'vue'

import { levelLabel, moduleLabel } from '@/modules/labs/components/profile/grantModules'

defineProps({
  managers: { type: Array, default: () => [] },
  /** user_id currently being written, or 'invite'. */
  saving: { type: [String, null], default: null },
  canInvite: { type: Boolean, default: false },
})

const emit = defineEmits(['edit', 'remove', 'invite'])

const confirming = ref(null)

function onRemove(manager) {
  if (confirming.value !== manager.user_id) {
    confirming.value = manager.user_id
    setTimeout(() => {
      if (confirming.value === manager.user_id) confirming.value = null
    }, 4000)
    return
  }
  confirming.value = null
  emit('remove', manager.user_id)
}

function joined(iso) {
  return new Date(iso).toLocaleDateString('ru-RU')
}
</script>

<template>
  <div class="lp-panel">
    <header class="lp-panel__head">
      <div class="min-w-0">
        <h2 class="lp-panel__title">Команда</h2>
        <p class="lp-panel__note">
          Уровень и разделы для каждого менеджера. Владелец видит всё и не настраивается.
        </p>
      </div>
      <button v-if="canInvite" type="button" class="lp-btn lp-btn--primary" @click="emit('invite')">
        Пригласить менеджера
      </button>
    </header>

    <p v-if="!managers.length" class="lp-empty">
      В организации пока нет менеджеров. Приглашение выдаёт доступ сразу — менеджер входит уже с
      теми правами, которые вы выбрали.
    </p>

    <div v-else class="lp-grid" role="table">
      <div class="lp-grid__head" role="row">
        <span role="columnheader">Сотрудник</span>
        <span role="columnheader">Уровень</span>
        <span role="columnheader">Разделы</span>
        <span role="columnheader">В команде с</span>
        <span role="columnheader" class="sr-only">Действия</span>
      </div>

      <div v-for="manager in managers" :key="manager.user_id" class="lp-grid__row" role="row">
        <span class="lp-cell lp-cell--who" role="cell">
          <span class="lp-who__mail" :title="manager.email">{{ manager.email }}</span>
          <span class="lp-who__meta">менеджер</span>
        </span>

        <span class="lp-cell" role="cell">
          <span class="lp-pill" :class="manager.access_level === 'read_only' ? 'is-quiet' : ''">
            {{ levelLabel(manager.access_level) }}
          </span>
        </span>

        <span class="lp-cell lp-cell--chips" role="cell">
          <span v-for="key in manager.modules" :key="key" class="lp-pill is-soft">
            {{ moduleLabel(key) }}
          </span>
          <span v-if="!manager.modules?.length" class="lp-who__meta">нет доступа</span>
        </span>

        <span class="lp-cell lp-who__meta" role="cell">{{ joined(manager.joined_at) }}</span>

        <span class="lp-cell lp-cell--act" role="cell">
          <button
            type="button"
            class="lp-btn"
            :disabled="saving === manager.user_id"
            @click="emit('edit', manager)"
          >
            Доступ
          </button>
          <button
            type="button"
            class="lp-btn lp-btn--danger"
            :class="confirming === manager.user_id ? 'is-armed' : ''"
            :disabled="saving === manager.user_id"
            @click="onRemove(manager)"
          >
            {{ confirming === manager.user_id ? 'Точно?' : 'Удалить' }}
          </button>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lp-grid__head,
.lp-grid__row {
  /* Every track but the two flexible ones is FIXED, and the header is a
     separate grid from each row — an `auto` action column would resolve wider
     on a row than on the header and take the alignment with it. */
  grid-template-columns: minmax(12rem, 2fr) 10rem minmax(10rem, 2fr) 7rem 9rem;
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
