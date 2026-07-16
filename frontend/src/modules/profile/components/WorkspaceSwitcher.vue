<script setup>
/**
 * Workspace switcher (dumb component).
 *
 * Renders every workspace as a selectable row; the active one is highlighted.
 * Emits `select` with the workspace id — the smart view applies the switch
 * (and reloads into the data views so no cross-workspace cache survives).
 */
defineProps({
  workspaces: { type: Array, default: () => [] },
  currentId: { type: String, default: null },
})

const emit = defineEmits(['select'])
</script>

<template>
  <section class="rounded-card border border-border-subtle bg-surface p-lg shadow-card">
    <h2 class="text-h2 font-bold text-primary">Рабочее пространство</h2>
    <p class="mt-xs text-tiny font-medium text-muted">
      Все данные мониторинга показываются в рамках выбранного пространства.
    </p>

    <p v-if="workspaces.length === 0" class="mt-md text-base font-body text-muted">
      Пока нет ни одного рабочего пространства.
    </p>

    <ul v-else class="mt-md flex flex-col gap-xs">
      <li v-for="ws in workspaces" :key="ws.id">
        <button
          type="button"
          class="flex w-full items-center justify-between rounded-btn border px-md py-sm text-left transition"
          :class="
            ws.id === currentId
              ? 'border-action bg-action/10 text-primary'
              : 'border-border-subtle text-primary hover:bg-hover'
          "
          @click="emit('select', ws.id)"
        >
          <span class="truncate text-base font-medium">{{ ws.name }}</span>
          <span
            v-if="ws.id === currentId"
            class="ml-md shrink-0 rounded-btn bg-action px-sm py-xs text-tiny font-semibold text-white"
          >
            Активно
          </span>
          <span v-else class="ml-md shrink-0 text-tiny font-medium text-action">
            Переключить
          </span>
        </button>
      </li>
    </ul>
  </section>
</template>
