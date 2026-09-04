<script setup>
/**
 * The owner's access panel: every manager, and what each may reach.
 *
 * Edits are staged per manager and saved explicitly. A switch that saved on
 * flip would fire three requests while an owner set up one person, and the
 * middle one would briefly be a grant they never intended to store.
 */
import { computed, reactive, ref } from 'vue'

import AccessGrantFields from '@/modules/profile/components/AccessGrantFields.vue'
import { MODULES } from '@/modules/profile/membersStore'

const props = defineProps({
  managers: { type: Array, required: true },
  saving: { type: String, default: null },
})
const emit = defineEmits(['save', 'remove'])

// Confirm-in-place rather than a modal: the id of the manager awaiting a second
// press. Removal is not reversible from here — re-inviting is a new invitation
// and a new grant — so it should not happen on one stray click.
const confirming = ref(null)

function onRemove(manager) {
  if (confirming.value !== manager.user_id) {
    confirming.value = manager.user_id
    return
  }
  confirming.value = null
  emit('remove', manager.user_id)
}

/** Staged edits, keyed by user id; absent means "unchanged". */
const drafts = reactive({})

function grantOf(manager) {
  return drafts[manager.user_id] ?? { accessLevel: manager.access_level, modules: manager.modules }
}

function onUpdate(manager, grant) {
  drafts[manager.user_id] = grant
}

function isDirty(manager) {
  const draft = drafts[manager.user_id]
  if (!draft) return false
  return (
    draft.accessLevel !== manager.access_level ||
    draft.modules.join() !== [...manager.modules].sort(byModuleOrder).join()
  )
}

function byModuleOrder(a, b) {
  return MODULES.findIndex((m) => m.key === a) - MODULES.findIndex((m) => m.key === b)
}

function onSave(manager) {
  emit('save', { userId: manager.user_id, grant: grantOf(manager) })
  delete drafts[manager.user_id]
}

const isEmpty = computed(() => props.managers.length === 0)
</script>

<template>
  <section class="rounded-card border border-border-subtle bg-surface p-lg shadow-card">
    <h2 class="text-h2 font-bold text-primary">Доступ менеджеров</h2>
    <p class="mt-xs text-tiny font-medium text-muted">
      Уровень и разделы для каждого менеджера. Владелец видит всё и не настраивается.
    </p>

    <p v-if="isEmpty" class="mt-md text-base text-muted">
      В организации пока нет менеджеров — пригласите первого ниже.
    </p>

    <ul v-else class="mt-md flex flex-col gap-md">
      <li
        v-for="manager in managers"
        :key="manager.user_id"
        class="rounded-card border border-border-subtle p-md"
      >
        <div class="flex items-center justify-between gap-md phone:flex-col phone:items-start">
          <span class="min-w-0 truncate text-base font-medium text-primary">
            {{ manager.email }}
          </span>
          <span class="text-tiny text-muted">
            в команде с {{ new Date(manager.joined_at).toLocaleDateString('ru-RU') }}
          </span>
        </div>

        <div class="mt-md">
          <AccessGrantFields
            :access-level="grantOf(manager).accessLevel"
            :modules="grantOf(manager).modules"
            :disabled="saving === manager.user_id"
            @update="(grant) => onUpdate(manager, grant)"
          />
        </div>

        <div class="mt-md flex items-center justify-between gap-md">
          <!-- Removing is what actually withdraws access from somebody who has
               already joined; revoking their invitation would not. Two presses,
               because it cannot be undone from this screen. -->
          <button
            type="button"
            class="remove-member"
            :disabled="saving === manager.user_id"
            @click="onRemove(manager)"
          >
            {{ confirming === manager.user_id ? 'Точно удалить?' : 'Удалить из компании' }}
          </button>

          <button
            type="button"
            class="rounded-btn bg-action px-md py-xs text-base font-semibold text-white transition-opacity disabled:opacity-50"
            :disabled="!isDirty(manager) || saving === manager.user_id"
            @click="onSave(manager)"
          >
            {{ saving === manager.user_id ? 'Сохраняем…' : 'Сохранить' }}
          </button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.remove-member {
  @apply text-tiny font-semibold transition disabled:cursor-not-allowed disabled:opacity-60;
  color: var(--ui-neg);
}
</style>
