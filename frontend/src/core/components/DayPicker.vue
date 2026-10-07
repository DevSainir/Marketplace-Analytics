<script setup>
/**
 * The one-day sibling of `PeriodSelector`: same frame (`CalendarShell`), same
 * grid, same paint, one month and no presets.
 *
 * Click the field → the month of the selected day opens → click a day → the
 * popover closes and `update:modelValue` fires with the ISO date.
 *
 * Lives in `core/` because a date is not a domain concept any module owns; the
 * finreports stock balance picks its snapshot day with it.
 */
import { computed, ref } from 'vue'

import CalendarMonthGrid from '@/core/components/CalendarMonthGrid.vue'
import CalendarShell from '@/core/components/CalendarShell.vue'
import { btnClass } from '@/core/utils/calendarHighlight'
import { TODAY_ISO, formatDay, useCalendarView } from '@/core/utils/calendarModel'

const props = defineProps({
  /** Selected day, ISO `YYYY-MM-DD`. */
  modelValue: { type: String, required: true },
  /** Latest pickable day (ISO); empty = today. */
  max: { type: String, default: '' },
  /**
   * Earliest pickable day (ISO); empty = no floor. The stock balance has one:
   * days before the first snapshot hold no data at all, and letting them be
   * picked would answer «нет остатков» to a question that was never asked.
   */
  min: { type: String, default: '' },
  label: { type: String, default: 'День' },
  ariaLabel: { type: String, default: 'Выбор дня' },
})
const emit = defineEmits(['update:modelValue'])

const open = ref(false)
const viewYear = ref(2000)
const viewMonth = ref(0)

const { monthsToShow, canGoNext, canGoPrev, shiftView, showEndingAt } = useCalendarView(
  viewYear,
  viewMonth,
  { count: () => 1, span: () => ({ lo: props.min, hi: props.max || TODAY_ISO }) },
)
const month = computed(() => monthsToShow.value[0])

/** One day is a range whose two ends coincide — painted the way a range's ends are. */
const dayClass = (cell) => btnClass(cell, { lo: props.modelValue, hi: props.modelValue }, TODAY_ISO)

function pickDay(cell) {
  if (cell.disabled) return
  open.value = false
  if (cell.iso !== props.modelValue) emit('update:modelValue', cell.iso)
}
</script>

<template>
  <CalendarShell
    v-model:open="open"
    :label="label"
    :aria-label="ariaLabel"
    :titles="[month.label]"
    :can-go-prev="canGoPrev"
    :can-go-next="canGoNext"
    @opening="showEndingAt(modelValue)"
    @shift="shiftView"
  >
    <template #trigger>
      <span>{{ formatDay(modelValue) }}</span>
    </template>

    <CalendarMonthGrid :cells="month.cells" :day-class="dayClass" @day-click="pickDay" />
  </CalendarShell>
</template>
