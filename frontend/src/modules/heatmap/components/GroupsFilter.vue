<script setup>
/**
 * "Groups" — the filter every page with "Categories" and "Brands" carries, and
 * where groups are made: its menu ends in "Add group", and every group
 * has a pencil that opens it for editing. The list of groups is where a seller
 * looks for them, so that is where they are managed.
 *
 * The list is `useGroupsStore`'s, so a group made here is in every other
 * page's menu at once. The choice — which groups narrow THIS page — is the
 * page's own `v-model`.
 *
 * Shown only to a caller the server lets read groups — anybody holding one of
 * the pages that carry this filter (`GROUP_MODULES`), which every page
 * rendering it is. "Add group" and ✎ only for one who may write: a read-only manager or a
 * guest in another company's workspace is refused by the server anyway.
 *
 * `cards` is what the editor offers; the heatmap passes its catalogue (ranked
 * by orders in its own window), any other page leaves it to the store.
 */
import { computed, onMounted, ref, watch } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import FilterMenu from '@/core/components/FilterMenu.vue'
import GroupDialog from '@/modules/heatmap/components/GroupDialog.vue'
import { useGroupsReadable, useGroupsStore } from '@/modules/heatmap/groupsStore'
import { useMembersStore, useWorkspaceStore } from '@/modules/profile'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  /** @type {Array<object>|null} The heatmap catalogue's cards; `null` loads the store's. */
  cards: { type: Array, default: null },
})
const emit = defineEmits(['update:modelValue'])

const store = useGroupsStore()
const members = useMembersStore()
const workspaces = useWorkspaceStore()
const readable = useGroupsReadable()
const writable = computed(() => members.canWrite && !workspaces.currentWorkspace?.is_guest)
const menu = ref(null)
const dialogOpen = ref(false)
const editing = ref(null)

const items = computed(() =>
  store.groups.map((group) => ({
    value: group.id,
    label: group.name,
    sub: `SKUs: ${group.nm_ids.length}`,
  })),
)
const editorCards = computed(() => props.cards ?? store.cards)

// A group deleted elsewhere leaves this page's choice — a filter by a group
// that no longer exists would quietly show nothing.
watch(
  () => store.groups,
  (groups) => {
    const alive = props.modelValue.filter((id) => groups.some((group) => group.id === id))
    if (alive.length !== props.modelValue.length) emit('update:modelValue', alive)
  },
)

// A list that fails to load reads as "No groups yet"; the page's own figures
// do not wait on it.
onMounted(() => {
  if (readable.value) store.load().catch(() => {})
})

/** The dialog takes over from the menu, so the menu gets out of its way. */
function openEditor(id = null) {
  menu.value?.close()
  editing.value = id ? store.groups.find((group) => group.id === id) : null
  store.error = ''
  dialogOpen.value = true
  if (!props.cards) store.loadCards().catch((err) => (store.error = extractErrorMessage(err)))
}

async function save(group) {
  if (await store.save(group)) dialogOpen.value = false
}

async function remove(id) {
  if (await store.remove(id)) dialogOpen.value = false
}
</script>

<template>
  <FilterMenu
    v-if="readable"
    ref="menu"
    label="Groups"
    :items="items"
    :model-value="modelValue"
    badge
    empty-text="No groups yet"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template v-if="writable" #action="{ item }">
      <button
        type="button"
        class="shrink-0 rounded-btn px-sm py-xs text-tiny text-muted transition hover:text-action"
        :aria-label="`Edit group ${item.label}`"
        @click="openEditor(item.value)"
      >
        ✎
      </button>
    </template>
    <template v-if="writable" #footer>
      <button type="button" class="text-tiny font-semibold text-action" @click="openEditor()">
        + Add group
      </button>
    </template>
  </FilterMenu>

  <GroupDialog
    :open="dialogOpen"
    :group="editing"
    :cards="editorCards"
    :busy="store.busy"
    :error="store.error"
    @close="dialogOpen = false"
    @save="save"
    @delete="remove"
  />
</template>
