<script setup>
/**
 * The quick presets in the period picker's footer — "7 days", "30 days",
 * "90 days", and "All time" when the page knows its first day or
 * "180 days" when it does not. The only presets in the app: no page draws its
 * own beside the calendar.
 *
 * Split out of `PeriodSelector` (a component is capped at 250 lines): the
 * calendar decides a range by two clicks, this decides one by one, and the
 * window each preset stands for is `calendarModel`'s, not this file's.
 *
 * At most one preset is marked — the one `activePreset` names. Both the window
 * a preset sets and the mark come from `presetWindow`, so the button that set
 * a window always recognises it.
 */
import { computed } from 'vue'

import { activePreset, presetWindow, presetsFor } from '@/core/utils/calendarModel'

const props = defineProps({
  /** The window on screen (ISO), to mark the preset that stands for it. */
  from: { type: String, default: '' },
  to: { type: String, default: '' },
  /** Whether the calendar is waiting for the second click of a range. */
  awaitingEnd: { type: Boolean, default: false },
  /** Day the presets end on (ISO); empty = today. */
  presetEnd: { type: String, default: '' },
  /** The page's first day (ISO); set, "180 days" gives way to "All time". */
  historyFrom: { type: String, default: '' },
  /** Longest window the page answers for; 0 = no limit. */
  maxDays: { type: Number, default: 0 },
})

/** `pick` carries the whole window, `{from, to}`. */
const emit = defineEmits(['pick'])

const bounds = computed(() => ({
  end: props.presetEnd,
  historyFrom: props.historyFrom,
  maxDays: props.maxDays,
}))
const presets = computed(() => presetsFor(props.historyFrom))
const active = computed(() => activePreset(props.from, props.to, bounds.value))

function pick(days) {
  emit('pick', presetWindow(days, bounds.value))
}
</script>

<template>
  <div class="mt-md border-t border-border-subtle pt-sm sm:flex sm:items-center sm:gap-xs">
    <span class="mb-xs block text-tiny text-muted sm:mb-0 sm:mr-auto">
      {{ awaitingEnd ? 'Pick the end of the period' : 'Quick pick:' }}
    </span>
    <!-- Four abreast need ~290px; a one-month popover has 252, so two by two. -->
    <div class="grid grid-cols-2 gap-xs sm:flex">
      <button
        v-for="preset in presets"
        :key="preset.days"
        type="button"
        class="preset-btn phone:min-h-11"
        :class="{ 'preset-btn--active': active === preset.days }"
        :aria-pressed="active === preset.days"
        @click="pick(preset.days)"
      >
        {{ preset.label }}
      </button>
    </div>
  </div>
</template>

<style scoped src="./styles/PeriodPresets.css"></style>
