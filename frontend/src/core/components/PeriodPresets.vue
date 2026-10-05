<script setup>
/**
 * The quick presets in the period picker's footer — «7 дней» … «180 дней», or
 * «Вся история» in place of the longest when the page knows its first day.
 *
 * Split out of `PeriodSelector` (a component is capped at 250 lines): the
 * calendar decides a range by two clicks, this decides one by one, and the
 * window each preset stands for is `calendarModel`'s, not this file's.
 */
import { computed } from 'vue'

import { presetWindow, presetsFor } from '@/core/utils/calendarModel'

const props = defineProps({
  /** Whether the calendar is waiting for the second click of a range. */
  awaitingEnd: { type: Boolean, default: false },
  /** Day the presets end on (ISO); empty = today. */
  presetEnd: { type: String, default: '' },
  /** The page's first day (ISO); set, «180 дней» gives way to «Вся история». */
  historyFrom: { type: String, default: '' },
})

/** `pick` carries the whole window, `{from, to}`. */
const emit = defineEmits(['pick'])

const presets = computed(() => presetsFor(props.historyFrom))

function pick(days) {
  emit('pick', presetWindow(days, props.presetEnd, props.historyFrom))
}
</script>

<template>
  <div class="mt-md flex items-center gap-xs border-t border-border-subtle pt-sm">
    <span class="mr-auto text-tiny text-muted">
      {{ awaitingEnd ? 'Выберите конец периода' : 'Быстрый выбор:' }}
    </span>
    <button
      v-for="preset in presets"
      :key="preset.days"
      type="button"
      class="preset-btn"
      @click="pick(preset.days)"
    >
      {{ preset.label }}
    </button>
  </div>
</template>

<style scoped src="./styles/PeriodSelector.css"></style>
