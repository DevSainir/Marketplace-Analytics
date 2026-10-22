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
import DataState from '@/core/components/DataState.vue'
import { confirmLabel, useConfirmClick } from '@/core/utils/confirmClick'
import { levelLabel, moduleLabel } from '@/modules/profile/components/grantModules'
import { formatMoscowDate } from '@/core/utils/moscow'

defineProps({
  /** The team is still being read — until then «no managers» would be a guess. */
  loading: { type: Boolean, default: false },
  managers: { type: Array, default: () => [] },
  /** user_id currently being written, or 'invite'. */
  saving: { type: [String, null], default: null },
  canInvite: { type: Boolean, default: false },
})

const emit = defineEmits(['edit', 'remove', 'invite'])

const removal = useConfirmClick()

function joined(iso) {
  return formatMoscowDate(iso)
}
</script>

<template>
  <div class="pf-panel">
    <header class="pf-panel__head">
      <div class="min-w-0">
        <h2 class="pf-panel__title">Команда</h2>
        <p class="pf-panel__note">Доступы</p>
      </div>
      <button v-if="canInvite" type="button" class="ui-btn ui-btn--primary" @click="emit('invite')">
        Пригласить менеджера
      </button>
    </header>

    <DataState v-if="loading && !managers.length" kind="loading" />
    <DataState
      v-else-if="!managers.length"
      kind="empty"
      text="В организации пока нет менеджеров"
      hint="Приглашение выдаёт доступ сразу — менеджер входит уже с теми правами, которые вы выбрали."
    />

    <div v-else class="pf-grid" role="table">
      <div class="pf-grid__head" role="row">
        <span role="columnheader">Сотрудник</span>
        <span role="columnheader">Уровень</span>
        <span role="columnheader">Разделы</span>
        <span role="columnheader">В команде с</span>
        <span role="columnheader" class="sr-only">Действия</span>
      </div>

      <div v-for="manager in managers" :key="manager.user_id" class="pf-grid__row" role="row">
        <span class="pf-cell pf-cell--who" role="cell">
          <span class="pf-who__mail" :title="manager.email">{{ manager.email }}</span>
          <span class="pf-who__meta">менеджер</span>
        </span>

        <span class="pf-cell" role="cell">
          <span class="ui-badge" :class="manager.access_level === 'read_only' ? 'is-quiet' : ''">
            {{ levelLabel(manager.access_level) }}
          </span>
        </span>

        <span class="pf-cell pf-cell--chips" role="cell">
          <span v-for="key in manager.modules" :key="key" class="ui-badge is-soft">
            {{ moduleLabel(key) }}
          </span>
          <span v-if="!manager.modules?.length" class="pf-who__meta">нет доступа</span>
        </span>

        <span class="pf-cell pf-who__meta" role="cell">{{ joined(manager.joined_at) }}</span>

        <span class="pf-cell pf-cell--act" role="cell">
          <button
            type="button"
            class="ui-btn ui-btn--ghost ui-btn--sm"
            :disabled="saving === manager.user_id"
            @click="emit('edit', manager)"
          >
            Доступ
          </button>
          <button
            type="button"
            class="ui-btn ui-btn--danger ui-btn--sm"
            :class="removal.isArmed(manager.user_id) ? 'is-armed' : ''"
            :disabled="saving === manager.user_id"
            @click="removal.press(manager.user_id, () => emit('remove', manager.user_id))"
          >
            {{ removal.isArmed(manager.user_id) ? confirmLabel('Delete') : 'Delete' }}
          </button>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pf-grid__head,
.pf-grid__row {
  /* Every track but the two flexible ones is FIXED, and the header is a
     separate grid from each row — an `auto` action column would resolve wider
     on a row than on the header and take the alignment with it. */
  grid-template-columns: minmax(12rem, 2fr) 10rem minmax(10rem, 2fr) 7rem 9rem;
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
