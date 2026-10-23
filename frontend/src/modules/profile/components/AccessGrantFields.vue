<script setup>
/**
 * The grant control: one level, and a switch per module.
 *
 * Styled for the drawer it lives in. Dumb: props in, one `update` event out;
 * the parent owns the saving.
 */
import { computed } from 'vue'

import { GRANT_LEVELS, GRANT_MODULES } from '@/modules/profile/components/grantModules'

const props = defineProps({
  accessLevel: { type: String, required: true },
  modules: { type: Array, required: true },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update'])

const enabled = computed(() => new Set(props.modules))

function setLevel(value) {
  emit('update', { accessLevel: value, modules: props.modules })
}

function toggleModule(key) {
  const next = new Set(props.modules)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  // Emitted in GRANT_MODULES order rather than click order, so two owners who
  // picked the same modules send the same payload.
  emit('update', {
    accessLevel: props.accessLevel,
    modules: GRANT_MODULES.filter((m) => next.has(m.key)).map((m) => m.key),
  })
}
</script>

<template>
  <div class="flex flex-col gap-lg">
    <fieldset class="flex flex-col gap-sm">
      <legend class="pf-legend">Access level</legend>
      <div class="grid grid-cols-2 gap-sm phone:grid-cols-1">
        <label
          v-for="level in GRANT_LEVELS"
          :key="level.value"
          class="pf-level"
          :class="[accessLevel === level.value ? 'is-on' : '', disabled ? 'is-off' : '']"
        >
          <input
            type="radio"
            class="sr-only"
            :checked="accessLevel === level.value"
            :disabled="disabled"
            @change="setLevel(level.value)"
          />
          <span class="text-base font-semibold">{{ level.label }}</span>
          <span class="text-tiny font-medium text-muted">{{ level.hint }}</span>
        </label>
      </div>
    </fieldset>

    <fieldset class="flex flex-col gap-sm">
      <legend class="pf-legend">Sections</legend>
      <label
        v-for="module in GRANT_MODULES"
        :key="module.key"
        class="pf-module"
        :class="disabled ? 'is-off' : ''"
      >
        <span class="min-w-0">
          <span class="block truncate text-base font-medium text-primary">{{ module.label }}</span>
          <span class="block truncate text-tiny text-muted">{{ module.hint }}</span>
        </span>
        <!-- A real checkbox styled as a switch: it keeps the keyboard and
             screen-reader behaviour a div with a click handler throws away. -->
        <span class="relative inline-flex">
          <input
            type="checkbox"
            class="sr-only"
            :checked="enabled.has(module.key)"
            :disabled="disabled"
            @change="toggleModule(module.key)"
          />
          <UiSwitch :on="enabled.has(module.key)" />
        </span>
      </label>
    </fieldset>
  </div>
</template>

<style scoped>
.pf-legend {
  @apply text-tiny font-semibold uppercase tracking-wide;
  color: var(--ui-faint);
}

.pf-level {
  @apply flex cursor-pointer flex-col gap-xs rounded-input border px-md py-sm transition;
  border-color: var(--ui-hairline);
  color: var(--ui-ink);
}

.pf-level:hover {
  border-color: var(--ui-action-line);
}

.pf-level.is-on {
  border-color: var(--ui-action);
  background: var(--ui-action-soft);
  color: var(--ui-action);
}

/* The same hairline the level cards carry. Without it the three module rows
   were the only unbounded things in the drawer, so the panel read as two
   framed choices followed by loose text. */
.pf-module {
  @apply flex cursor-pointer items-center justify-between gap-md rounded-input border px-md py-sm transition;
  border-color: var(--ui-hairline);
}

.pf-module:hover {
  background: var(--ui-sunk);
}

.is-off {
  @apply cursor-not-allowed opacity-60;
}
</style>
