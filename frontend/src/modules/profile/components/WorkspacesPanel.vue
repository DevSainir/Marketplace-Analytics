<script setup>
/**
 * Workspaces: which one you are looking at, and — for an owner — what exists.
 *
 * One block, replacing «Кабинет» and «Управление кабинетами».
 * They listed the same workspaces twice, one to switch between and one to
 * administer, so an owner read every name on the page twice and had to know
 * which copy carried which button.
 *
 * Everything a workspace can have done to it is now on its own row:
 * «Переключить», «Токены WB», «Удалить». The active row shows «Активно»
 * instead of a switch that would do nothing.
 *
 * `canManage` is what a MANAGER does not have. They still need to switch — the
 * whole app is scoped to the chosen workspace — but creating, deleting and
 * WB tokens are an owner's, matching `_owner_only` on those routes. Without
 * the flag this merge would have handed every manager the delete button.
 */
import { ref } from 'vue'

import WorkspaceTokensForm from '@/modules/profile/components/WorkspaceTokensForm.vue'

defineProps({
  workspaces: { type: Array, default: () => [] },
  currentId: { type: String, default: null },
  /** Map of workspace id -> token status, lazy-loaded when a row is expanded. */
  tokenStatuses: { type: Object, default: () => ({}) },
  busy: { type: Boolean, default: false },
  canManage: { type: Boolean, default: false },
})

const emit = defineEmits(['select', 'create', 'remove', 'expand', 'save-tokens'])

const newName = ref('')
const expandedId = ref(null)
const confirmDeleteId = ref(null)

function onCreate() {
  const name = newName.value.trim()
  if (!name) return
  emit('create', name)
  newName.value = ''
}

function toggleExpand(id) {
  expandedId.value = expandedId.value === id ? null : id
  confirmDeleteId.value = null
  if (expandedId.value) emit('expand', id)
}

function onRemove(id) {
  // Two presses: deleting a workspace hides every SKU under it.
  if (confirmDeleteId.value !== id) {
    confirmDeleteId.value = id
    return
  }
  confirmDeleteId.value = null
  emit('remove', id)
}
</script>

<template>
  <section class="rounded-card border border-border-subtle bg-surface p-lg shadow-card">
    <h2 class="text-h2 font-bold text-primary">Кабинеты</h2>
    <p class="mt-xs text-tiny font-medium text-muted">
      <template v-if="canManage">
        Все данные показываются в рамках выбранного кабинета. Токены WB хранятся в базе в
        зашифрованном виде и никогда не показываются повторно.
      </template>
      <template v-else> Все данные показываются в рамках выбранного кабинета. </template>
    </p>

    <!-- Above the list, as the thing you do before there is a list to read. -->
    <form v-if="canManage" class="mt-md flex gap-sm phone:flex-col" @submit.prevent="onCreate">
      <input
        v-model="newName"
        type="text"
        placeholder="Название нового кабинета"
        class="w-full rounded-input border border-border-subtle bg-canvas px-md py-sm text-base text-primary placeholder:text-muted focus:border-action focus:outline-none phone:min-h-11"
      />
      <button
        type="submit"
        :disabled="busy || !newName.trim()"
        class="shrink-0 rounded-btn bg-action px-md py-sm text-base font-semibold text-white transition hover:bg-action-hover disabled:opacity-50 phone:min-h-11"
      >
        Создать
      </button>
    </form>

    <p v-if="workspaces.length === 0" class="mt-md text-base font-body text-muted">
      Пока нет ни одного кабинета.
    </p>

    <ul v-else class="mt-md flex flex-col gap-sm">
      <li v-for="ws in workspaces" :key="ws.id" class="rounded-card border border-border-subtle">
        <!-- Name opposite its actions needs ~420px before the name truncates to
             nothing («И…»), so on a phone the row becomes two: which workspace,
             then what you can do to it. -->
        <div
          class="flex items-center justify-between gap-sm px-md py-sm phone:flex-col phone:items-stretch phone:gap-xs"
        >
          <span class="flex min-w-0 items-center gap-xs">
            <span class="truncate text-base font-medium text-primary">{{ ws.name }}</span>
            <span v-if="ws.is_primary" class="ws-badge ws-badge-soft">основное</span>
          </span>

          <div class="flex shrink-0 items-center gap-xs phone:justify-between">
            <!-- The one row that cannot be switched to is the one you are on. -->
            <span v-if="ws.id === currentId" class="ws-badge ws-badge-active">Активно</span>
            <button v-else type="button" class="ws-action" @click="emit('select', ws.id)">
              Переключить
            </button>

            <template v-if="canManage">
              <button type="button" class="ws-action" @click="toggleExpand(ws.id)">
                {{ expandedId === ws.id ? 'Скрыть токены' : 'Токены WB' }}
              </button>
              <button
                type="button"
                :disabled="busy"
                class="ws-action ws-action-danger"
                :class="confirmDeleteId === ws.id ? 'is-confirming' : ''"
                @click="onRemove(ws.id)"
              >
                {{ confirmDeleteId === ws.id ? 'Точно удалить?' : 'Удалить' }}
              </button>
            </template>
          </div>
        </div>

        <div
          v-if="canManage && expandedId === ws.id"
          class="border-t border-border-subtle px-md py-md"
        >
          <WorkspaceTokensForm
            :is-primary="ws.is_primary"
            :configured="tokenStatuses[ws.id]?.configured ?? []"
            :saving="busy"
            @save="(tokens) => emit('save-tokens', { workspaceId: ws.id, tokens })"
          />
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.ws-badge {
  @apply shrink-0 rounded-btn px-sm py-xs text-tiny font-semibold whitespace-nowrap;
}

.ws-badge-soft {
  background-color: color-mix(in srgb, var(--ui-action) 10%, transparent);
  color: var(--ui-action);
}

.ws-badge-active {
  background-color: var(--ui-action);
  color: #fff;
}

.ws-action {
  @apply rounded-btn px-md py-xs text-tiny font-medium transition disabled:cursor-not-allowed disabled:opacity-50 phone:min-h-11 phone:flex-1;
  color: var(--ui-action);
}

.ws-action:hover:not(:disabled) {
  background-color: color-mix(in srgb, var(--ui-action) 10%, transparent);
}

.ws-action-danger {
  color: var(--ui-neg);
}

.ws-action-danger:hover:not(:disabled) {
  background-color: color-mix(in srgb, var(--ui-neg) 10%, transparent);
}

.ws-action-danger.is-confirming {
  background-color: var(--ui-neg);
  color: #fff;
}
</style>
