<script setup>
/**
 * Single-day picker in the design system's calendar language — the one-date
 * sibling of PeriodSelector.vue (same trigger, popover, month grid, day and
 * nav styles; no native `<input type=date>` — its calendar is off-brand).
 *
 * Click the field → one month opens on the selected date → click a day →
 * the popover closes and `update:modelValue` fires with the ISO date.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { isoLocalDate } from '@/core/utils/dates'

const props = defineProps({
  /** Selected day, ISO `YYYY-MM-DD`. */
  modelValue: { type: String, required: true },
  /** Latest pickable day (ISO); later cells are disabled. */
  max: { type: String, default: () => isoLocalDate(new Date()) },
  ariaLabel: { type: String, default: 'Выбор дня' },
})
const emit = defineEmits(['update:modelValue'])

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const MONTHS = [
  'Январь',
  'Февраль',
  'Март',
  'Апрель',
  'Май',
  'Июнь',
  'Июль',
  'Август',
  'Сентябрь',
  'Октябрь',
  'Ноябрь',
  'Декабрь',
]

const todayIso = isoLocalDate(new Date())

const root = ref(null)
const open = ref(false)
const viewYear = ref(2000)
const viewMonth = ref(0)

/** "2026-07-11" → "11.07.2026" for the trigger display. */
function fmt(iso) {
  if (!iso) return '—'
  const [y, m, d] = iso.split('-')
  return `${d}.${m}.${y}`
}

/** A 6×7 grid of day cells for one month (leading/trailing days dimmed). */
function buildMonth(year, month) {
  const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7 // Mon = 0
  const start = new Date(year, month, 1 - firstWeekday)
  const cells = []
  for (let i = 0; i < 42; i += 1) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)
    const iso = isoLocalDate(d)
    cells.push({
      iso,
      day: d.getDate(),
      inMonth: d.getMonth() === month,
      disabled: iso > props.max,
    })
  }
  return cells
}

const month = computed(() => {
  const d = new Date(viewYear.value, viewMonth.value, 1)
  return {
    label: `${MONTHS[d.getMonth()]} ${d.getFullYear()}`,
    cells: buildMonth(d.getFullYear(), d.getMonth()),
  }
})

// The view may reach the max month, never beyond (no future-only view).
const canGoNext = computed(() => {
  const [y, m] = props.max.split('-').map(Number)
  return new Date(viewYear.value, viewMonth.value + 1, 1) <= new Date(y, m - 1, 1)
})

function shiftView(delta) {
  const d = new Date(viewYear.value, viewMonth.value + delta, 1)
  viewYear.value = d.getFullYear()
  viewMonth.value = d.getMonth()
}

function btnClass(cell) {
  if (cell.disabled) return 'text-border-subtle cursor-not-allowed'
  if (cell.iso === props.modelValue) return 'bg-action text-white font-semibold shadow-soft'
  const base = cell.inMonth ? 'text-primary' : 'text-muted'
  const todayRing = cell.iso === todayIso ? 'ring-1 ring-inset ring-action/40' : ''
  return `${base} ${todayRing} hover:bg-action/15`
}

function toggle() {
  if (open.value) {
    open.value = false
    return
  }
  const [y, m] = (props.modelValue || todayIso).split('-').map(Number)
  viewYear.value = y
  viewMonth.value = m - 1
  open.value = true
}

function pickDay(cell) {
  if (cell.disabled) return
  open.value = false
  if (cell.iso !== props.modelValue) emit('update:modelValue', cell.iso)
}

function onDocPointer(event) {
  if (open.value && root.value && !root.value.contains(event.target)) open.value = false
}
function onKey(event) {
  if (event.key === 'Escape') open.value = false
}
onMounted(() => {
  document.addEventListener('mousedown', onDocPointer)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocPointer)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="root" class="relative inline-block">
    <button
      type="button"
      class="flex h-8 items-center gap-xs rounded-input border bg-surface px-sm text-tiny tabular-nums text-primary shadow-soft transition-colors hover:border-action/60"
      :class="open ? 'border-action ring-2 ring-action/20' : 'border-border-subtle'"
      :aria-label="ariaLabel"
      @click="toggle"
    >
      <svg
        class="h-3.5 w-3.5 shrink-0 text-muted"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        aria-hidden="true"
      >
        <rect x="1.75" y="2.75" width="12.5" height="11.5" rx="2" />
        <path d="M1.75 6.25h12.5M5 1.25v3M11 1.25v3" />
      </svg>
      <span>{{ fmt(modelValue) }}</span>
    </button>

    <transition name="cal">
      <div
        v-if="open"
        class="absolute left-0 top-[calc(100%+6px)] z-40 rounded-card border border-border-subtle bg-surface p-md shadow-card"
        role="dialog"
        :aria-label="ariaLabel"
      >
        <div class="mb-sm flex items-center">
          <button
            type="button"
            class="nav-btn"
            aria-label="Предыдущий месяц"
            @click="shiftView(-1)"
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75">
              <path d="M10 3.5 5.5 8l4.5 4.5" />
            </svg>
          </button>
          <div class="flex-1 px-sm text-center text-base font-semibold text-primary">
            {{ month.label }}
          </div>
          <button
            type="button"
            class="nav-btn"
            :disabled="!canGoNext"
            aria-label="Следующий месяц"
            @click="shiftView(1)"
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75">
              <path d="M6 3.5 10.5 8 6 12.5" />
            </svg>
          </button>
        </div>

        <div class="calendar-grid">
          <div v-for="w in WEEKDAYS" :key="w" class="weekday">{{ w }}</div>
          <div v-for="cell in month.cells" :key="cell.iso" class="day-wrap">
            <button
              type="button"
              class="day"
              :class="btnClass(cell)"
              :disabled="cell.disabled"
              @click="pickDay(cell)"
            >
              {{ cell.day }}
            </button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
/* Same calendar metrics as PeriodSelector.vue — one shared visual language. */
.calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, 2.25rem);
  grid-auto-rows: 2.25rem;
}

.weekday {
  display: grid;
  place-items: center;
  height: 1.75rem;
  font-size: 0.6875rem; /* micro */
  font-weight: 500;
  text-transform: uppercase;
  color: #858585; /* muted */
}

.day-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 2.25rem;
  width: 2.25rem;
}

.day {
  display: grid;
  place-items: center;
  height: 2.25rem;
  width: 2.25rem;
  border-radius: 9999px;
  font-size: 0.875rem; /* base */
  font-variant-numeric: tabular-nums;
  transition:
    background-color 0.12s ease,
    color 0.12s ease;
}
.day:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--color-action, #007e76) 45%, transparent);
  outline-offset: -2px;
}

.nav-btn {
  display: grid;
  place-items: center;
  height: 1.75rem;
  width: 1.75rem;
  border-radius: 6px;
  color: #101010;
  transition: background-color 0.12s ease;
}
.nav-btn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--color-action, #007e76) 12%, transparent);
}
.nav-btn:disabled {
  color: #d0d0d0;
  cursor: not-allowed;
}
.nav-btn svg {
  height: 1rem;
  width: 1rem;
}

.cal-enter-active,
.cal-leave-active {
  transition:
    opacity 0.14s ease,
    transform 0.14s ease;
}
.cal-enter-from,
.cal-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
