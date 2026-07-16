<script setup>
/**
 * Workspace administration panel (dumb component; rendered for devs only).
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
    <div class="flex items-center gap-sm">
      <h2 class="text-h2 font-bold text-primary">Управление пространствами</h2>
      <span class="rounded-btn bg-accent-indigo/10 px-sm py-xs text-tiny font-semibold text-accent-indigo">
        dev
      </span>
    </div>
    <p class="mt-xs text-tiny font-medium text-muted">
      Создание и удаление рабочих пространств, токены WB API. Токены хранятся в
      базе в зашифрованном виде и никогда не показываются повторно.
    </p>

    <!-- Create -->
    <form class="mt-md flex gap-sm" @submit.prevent="onCreate">
      <input
        v-model="newName"
        type="text"
        placeholder="Название нового пространства"
        class="w-full rounded-input border border-border-subtle bg-canvas px-md py-sm text-base text-primary placeholder:text-muted focus:border-action focus:outline-none"
      />
      <button
        type="submit"
        :disabled="busy || !newName.trim()"
        class="shrink-0 rounded-btn bg-action px-md py-sm text-base font-semibold text-white transition hover:bg-action-hover disabled:opacity-50"
      >
        Создать
      </button>
    </form>

    <!-- Workspace list with per-workspace token editors -->
    <ul class="mt-md flex flex-col gap-sm">
      <li
        v-for="ws in workspaces"
        :key="ws.id"
        class="rounded-card border border-border-subtle"
      >
        <div class="flex items-center justify-between gap-sm px-md py-sm">
          <span class="flex min-w-0 items-center gap-xs">
            <span class="truncate text-base font-medium text-primary">{{ ws.name }}</span>
            <span
              v-if="ws.is_primary"
              class="shrink-0 rounded-btn bg-action/10 px-sm py-xs text-tiny font-semibold text-action"
            >
              основное
            </span>
          </span>
          <div class="flex shrink-0 items-center gap-xs">
            <button
              type="button"
              class="rounded-btn px-md py-xs text-tiny font-medium text-action transition hover:bg-action/10"
              @click="toggleExpand(ws.id)"
            >
              {{ expandedId === ws.id ? 'Скрыть токены' : 'Токены WB' }}
            </button>
            <button
              type="button"
              :disabled="busy"
              class="rounded-btn px-md py-xs text-tiny font-medium transition disabled:opacity-50"
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

        <div
          v-if="expandedId === ws.id"
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
