<script setup>
/**
 * Single-day picker in the design system's calendar language — the one-date
 * sibling of PeriodSelector.vue: the two share `CalendarMonthGrid` outright and
 * still mirror each other's trigger and nav styling (no native
 * `<input type=date>` — its calendar is off-brand).
 *
 * Click the field → one month opens on the selected date → click a day →
 * the popover closes and `update:modelValue` fires with the ISO date.
 *
 * Lives in `core/` because two modules pick days with it now — monitoring's
 * stock comparison and the finreports stock balance — and a date is not a
 * domain concept either of them owns.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import CalendarMonthGrid from '@/core/components/CalendarMonthGrid.vue'
import { isoLocalDate } from '@/core/utils/dates'

const props = defineProps({
  /** Selected day, ISO `YYYY-MM-DD`. */
  modelValue: { type: String, required: true },
  /** Latest pickable day (ISO); later cells are disabled. */
  max: { type: String, default: () => isoLocalDate(new Date()) },
  /**
   * Earliest pickable day (ISO); earlier cells are disabled. Empty = no floor.
   * The stock balance has one: days before the first snapshot hold no data at
   * all, and letting them be picked would answer «нет остатков» to a question
   * that was never asked.
   */
  min: { type: String, default: '' },
  ariaLabel: { type: String, default: 'Выбор дня' },
})
const emit = defineEmits(['update:modelValue'])

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
      disabled: iso > props.max || (!!props.min && iso < props.min),
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

        <CalendarMonthGrid :cells="month.cells" :day-class="btnClass" @day-click="pickDay" />
      </div>
    </transition>
  </div>
</template>

<style scoped src="./styles/DayPicker.css"></style>
