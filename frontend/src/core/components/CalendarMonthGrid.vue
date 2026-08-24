<script setup>
/**
 * One month drawn as a 6×7 grid of day buttons, under a Monday-first weekday row.
 *
 * The shared half of the two calendars in `core/`: PeriodSelector renders a pair
 * of these side by side, DayPicker one. Both had the same markup and the same
 * metrics, and «same calendar metrics as the other one» is a comment, not a
 * guarantee — an edit to one grid used to leave the other behind.
 *
 * Deliberately knows nothing about selection: the cells arrive built (from
 * `buildMonth`/`useCalendarView`), the paint arrives as two class functions, and
 * a click or a hover leaves as an event. That is what lets a range picker and a
 * single-day picker share it without either one's highlighting rules leaking in.
 */
import { WEEKDAYS } from '@/core/utils/calendarModel'

defineProps({
  /** The month's 42 cells: `{ iso, day, inMonth, disabled }`. */
  cells: { type: Array, required: true },
  /** Wrapper classes for a cell — the range band, when the caller draws one. */
  wrapClass: { type: Function, default: () => '' },
  /** Day-button classes for a cell: selection, today, disabled. */
  dayClass: { type: Function, default: () => '' },
})
defineEmits(['day-click', 'day-hover'])
</script>

<template>
  <div class="calendar-grid">
    <div v-for="w in WEEKDAYS" :key="w" class="weekday">{{ w }}</div>
    <div v-for="cell in cells" :key="cell.iso" class="day-wrap" :class="wrapClass(cell)">
      <button
        type="button"
        class="day"
        :class="dayClass(cell)"
        :disabled="cell.disabled"
        @click="$emit('day-click', cell)"
        @mouseenter="$emit('day-hover', cell)"
      >
        {{ cell.day }}
      </button>
    </div>
  </div>
</template>

<style scoped src="./styles/CalendarMonthGrid.css"></style>
