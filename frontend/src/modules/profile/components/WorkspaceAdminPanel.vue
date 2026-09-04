<script setup>
/**
 * Workspace administration panel (dumb component; rendered for owners and devs).
 *
 * Create/delete workspaces and manage their WB tokens. All data comes in as
 * props; every action is emitted upward — the smart ProfileView talks to the
 * store. One workspace at a time can be expanded to edit its tokens; the
 * `expand` event lets the view lazy-load that workspace's token status.
 */
import { ref } from 'vue'

import WorkspaceTokensForm from '@/modules/profile/components/WorkspaceTokensForm.vue'

defineProps({
  workspaces: { type: Array, default: () => [] },
  /** Map of workspace id -> token status ({is_primary, configured}), lazy on expand. */
  tokenStatuses: { type: Object, default: () => ({}) },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['create', 'remove', 'expand', 'save-tokens'])

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
  // Two-step confirmation: deleting a workspace hides all its SKUs.
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
    <!-- No «dev» badge: this panel is an owner's now, not a developer tool.
         `POST /v1/workspaces` is `_owner_only`, so the label named a role that
         was never the one the endpoint checks. -->
    <h2 class="text-h2 font-bold text-primary">Управление пространствами</h2>
    <p class="mt-xs text-tiny font-medium text-muted">
      Создание и удаление рабочих пространств, токены WB API. Токены хранятся в базе в зашифрованном
      виде и никогда не показываются повторно.
    </p>

    <!-- Create -->
    <!-- Side by side, the button leaves the field too narrow to read a name
         back on a phone, so the pair stacks. -->
    <form class="mt-md flex gap-sm phone:flex-col" @submit.prevent="onCreate">
      <input
        v-model="newName"
        type="text"
        placeholder="Название нового пространства"
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

    <!-- Workspace list with per-workspace token editors -->
    <ul class="mt-md flex flex-col gap-sm">
      <li v-for="ws in workspaces" :key="ws.id" class="rounded-card border border-border-subtle">
        <!-- Name opposite its two actions needs ~420px before the name starts
             truncating to nothing («И…»), so on a phone the row becomes two:
             the workspace it is, then what you can do to it. -->
        <div
          class="flex items-center justify-between gap-sm px-md py-sm phone:flex-col phone:items-stretch phone:gap-xs"
        >
          <span class="flex min-w-0 items-center gap-xs">
            <span class="truncate text-base font-medium text-primary">{{ ws.name }}</span>
            <span
              v-if="ws.is_primary"
              class="shrink-0 rounded-btn bg-action/10 px-sm py-xs text-tiny font-semibold text-action"
            >
              основное
            </span>
          </span>
          <div class="flex shrink-0 items-center gap-xs phone:justify-between">
            <button
              type="button"
              class="rounded-btn px-md py-xs text-tiny font-medium text-action transition hover:bg-action/10 phone:min-h-11 phone:flex-1"
              @click="toggleExpand(ws.id)"
            >
              {{ expandedId === ws.id ? 'Скрыть токены' : 'Токены WB' }}
            </button>
            <button
              type="button"
              :disabled="busy"
              class="rounded-btn px-md py-xs text-tiny font-medium transition disabled:opacity-50 phone:min-h-11 phone:flex-1"
              :class="
                confirmDeleteId === ws.id
                  ? 'bg-status-negative text-white hover:bg-status-negative/80'
                  : 'text-status-negative hover:bg-status-negative/10'
              "
              @click="onRemove(ws.id)"
            >
              {{ confirmDeleteId === ws.id ? 'Точно удалить?' : 'Удалить' }}
            </button>
          </div>
        </div>

        <div v-if="expandedId === ws.id" class="border-t border-border-subtle px-md py-md">
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
