<script setup>
/**
 * The grant control: one level, and a switch per module.
 *
 * Shared by the manager list and the invite form on purpose — the two must
 * offer exactly the same choices, and the bug that shape prevents is an invite
 * form granting a module the list cannot show or the guard does not know.
 *
 * Dumb: props in, one `update` event out. The parent owns the saving.
 */
import { computed } from 'vue'

import { MODULES } from '@/modules/profile/membersStore'

const props = defineProps({
  accessLevel: { type: String, required: true },
  modules: { type: Array, required: true },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update'])

const LEVELS = [
  { value: 'read_write', label: 'Чтение и запись' },
  { value: 'read_only', label: 'Только чтение' },
]

const enabled = computed(() => new Set(props.modules))

function setLevel(value) {
  emit('update', { accessLevel: value, modules: props.modules })
}

function toggleModule(key) {
  const next = new Set(props.modules)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  // Emitted in MODULES order rather than click order, so two owners who picked
  // the same modules send the same payload.
  emit('update', {
    accessLevel: props.accessLevel,
    modules: MODULES.filter((m) => next.has(m.key)).map((m) => m.key),
  })
}
</script>

<template>
  <div class="flex flex-col gap-md">
    <fieldset class="flex flex-col gap-xs">
      <legend class="text-tiny font-medium text-muted">Уровень доступа</legend>
      <div class="flex gap-xs phone:flex-col">
        <label
          v-for="level in LEVELS"
          :key="level.value"
          class="flex flex-1 cursor-pointer items-center gap-xs rounded-btn border px-sm py-xs text-base transition-colors"
          :class="[
            accessLevel === level.value
              ? 'border-action bg-action/10 font-semibold text-action'
              : 'border-border-subtle text-primary hover:bg-canvas',
            disabled ? 'cursor-not-allowed opacity-60' : '',
          ]"
        >
          <input
            type="radio"
            class="sr-only"
            :checked="accessLevel === level.value"
            :disabled="disabled"
            @change="setLevel(level.value)"
          />
          {{ level.label }}
        </label>
      </div>
    </fieldset>

    <fieldset class="flex flex-col gap-xs">
      <legend class="text-tiny font-medium text-muted">Разделы</legend>
      <label
        v-for="module in MODULES"
        :key="module.key"
        class="flex cursor-pointer items-center justify-between gap-md rounded-btn px-sm py-xs hover:bg-canvas"
        :class="disabled ? 'cursor-not-allowed opacity-60' : ''"
      >
        <span class="min-w-0">
          <span class="block truncate text-base font-medium text-primary">{{ module.label }}</span>
          <span class="block truncate text-tiny text-muted">{{ module.hint }}</span>
        </span>
        <!-- A real checkbox styled as a switch: it keeps the keyboard and
             screen-reader behaviour a div with a click handler throws away. -->
        <span
          class="relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors"
          :class="enabled.has(module.key) ? 'bg-action' : 'bg-border-subtle'"
        >
          <input
            type="checkbox"
            class="sr-only"
            :checked="enabled.has(module.key)"
            :disabled="disabled"
            @change="toggleModule(module.key)"
          />
          <span
            class="inline-block h-5 w-5 rounded-full bg-surface shadow-card transition-transform"
            :class="enabled.has(module.key) ? 'translate-x-5' : 'translate-x-0.5'"
          />
        </span>
      </label>
    </fieldset>
  </div>
</template>
