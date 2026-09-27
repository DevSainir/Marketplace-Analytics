<script setup>
/**
 * Compact workspace switcher for the header (dumb dropdown).
 *
 * Module-agnostic like the header that hosts it: workspaces come in as props,
 * picking one emits `select` and App.vue does the actual tenancy switch. The
 * expanded card list on the profile page stays as the full-size counterpart.
 */
import { computed, ref } from 'vue'

const props = defineProps({
  workspaces: { type: Array, default: () => [] },
  currentId: { type: String, default: null },
})

const emit = defineEmits(['select'])

const root = ref(null)
const open = ref(false)

const current = computed(() => props.workspaces.find((w) => w.id === props.currentId) ?? null)

function close() {
  open.value = false
}

/** Close only when focus leaves the whole menu (item clicks keep it). */
function onFocusOut(event) {
  if (!root.value?.contains(event.relatedTarget)) close()
}

function onSelect(workspace) {
  close()
  if (workspace.id === props.currentId) return
  emit('select', workspace.id)
}
</script>

<template>
  <div
    v-if="workspaces.length"
    ref="root"
    class="relative"
    @focusout="onFocusOut"
    @keydown.esc="close"
  >
    <button
      type="button"
      class="flex h-8 max-w-[10rem] items-center gap-xs rounded-btn border border-border-subtle bg-canvas px-sm text-tiny font-medium text-primary transition hover:border-action hover:text-action phone:max-w-[6.5rem]"
      :aria-expanded="open"
      aria-haspopup="listbox"
      :title="current?.name || 'Кабинет'"
      @click="open = !open"
    >
      <svg
        class="h-3.5 w-3.5 flex-none text-muted"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-5h6v5" />
      </svg>
      <span class="truncate">{{ current?.name || 'Кабинет' }}</span>
      <svg
        class="h-3.5 w-3.5 flex-none text-muted transition"
        :class="open ? 'rotate-180' : ''"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="m6 9 6 6 6-6" />
      </svg>
    </button>

    <Transition
      enter-active-class="transition duration-100 ease-out"
      enter-from-class="-translate-y-1 opacity-0"
      leave-active-class="transition duration-75 ease-in"
      leave-to-class="-translate-y-1 opacity-0"
    >
      <div
        v-if="open"
        class="absolute right-0 top-full z-20 mt-xs max-h-80 w-56 overflow-y-auto rounded-card bg-surface shadow-card"
        role="listbox"
      >
        <p class="px-md pb-xs pt-sm text-tiny font-medium text-muted">Кабинет</p>
        <ul class="divide-y divide-border-subtle">
          <li v-for="workspace in workspaces" :key="workspace.id">
            <button
              type="button"
              role="option"
              :aria-selected="workspace.id === currentId"
              class="flex w-full items-center gap-sm px-md py-sm text-left transition hover:bg-action/10 phone:py-md"
              :class="workspace.id === currentId ? 'bg-action/10' : ''"
              @click="onSelect(workspace)"
            >
              <span class="min-w-0 flex-1 truncate text-base font-medium text-primary">
                {{ workspace.name }}
              </span>
              <span
                v-if="workspace.is_guest"
                class="flex-none text-tiny text-muted"
                title="Кабинет другой организации — только просмотр"
              >
                просмотр
              </span>
              <svg
                v-if="workspace.id === currentId"
                class="h-4 w-4 flex-none text-action"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2.2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="m5 12 5 5L19 7" />
              </svg>
            </button>
          </li>
        </ul>
      </div>
    </Transition>
  </div>
</template>
