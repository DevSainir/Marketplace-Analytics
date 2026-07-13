<script setup>
/**
 * Custom date-range picker: ONE control that opens a single calendar popover.
 *
 * Flow: click the field → the calendar opens → click the start day → click the
 * end day → the popover closes with the range set (the parent still applies it
 * with «Применить»). Between the two clicks, hovering previews the range. Quick
 * presets (7 / 30 / 90 дней) set a rolling window ending yesterday.
 *
 * Fully custom (no native `<input type=date>` — its calendar is off-brand):
 * styled with the design system, action-color endpoints and a soft action
 * range band, on-brand hover/focus. Dates are compared as ISO strings
 * (`YYYY-MM-DD` sorts lexicographically), so no timezone math is needed.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { isoDaysAgo, isoLocalDate } from '@/core/utils/dates'

const props = defineProps({
  from: { type: String, required: true },
  to: { type: String, required: true },
})
const emit = defineEmits(['update:from', 'update:to'])

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const MONTHS = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]
const PRESETS = [
  { label: '7 дней', days: 7 },
  { label: '30 дней', days: 30 },
  { label: '90 дней', days: 90 },
]

const today = new Date()
const todayIso = isoLocalDate(today)

// --- popover + view state ----------------------------------------------
const root = ref(null)
const open = ref(false)
const viewYear = ref(today.getFullYear())
const viewMonth = ref(today.getMonth()) // 0-based, the LEFT month of the pair

// --- selection state ---------------------------------------------------
// `phase` is 'start' until the first click of a new range, then 'end'.
const pendingStart = ref(props.from)
const pendingEnd = ref(props.to)
const phase = ref('start')
const hover = ref(null)

/** "2026-07-11" → "11.07.2026" for the trigger + header display. */
function fmt(iso) {
  if (!iso) return '—'
  const [y, m, d] = iso.split('-')
  return `${d}.${m}.${y}`
}

// --- calendar model ----------------------------------------------------
/** A 6×7 grid of day cells for one month (leading/trailing days dimmed). */
function buildMonth(year, month) {
  const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7 // Mon = 0
  const start = new Date(year, month, 1 - firstWeekday)
  const cells = []
  for (let i = 0; i < 42; i += 1) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)
    const iso = isoLocalDate(d)
    cells.push({ iso, day: d.getDate(), inMonth: d.getMonth() === month, disabled: iso > todayIso })
  }
  return cells
}

const monthsToShow = computed(() =>
  [0, 1].map((offset) => {
    const d = new Date(viewYear.value, viewMonth.value + offset, 1)
    return { label: `${MONTHS[d.getMonth()]} ${d.getFullYear()}`, cells: buildMonth(d.getFullYear(), d.getMonth()) }
  }),
)

// The right month may reach the current month, never beyond (no future-only view).
const canGoNext = computed(
  () => new Date(viewYear.value, viewMonth.value + 1, 1) < new Date(today.getFullYear(), today.getMonth(), 1),
)

function shiftView(delta) {
  const d = new Date(viewYear.value, viewMonth.value + delta, 1)
  viewYear.value = d.getFullYear()
  viewMonth.value = d.getMonth()
}

// --- range highlighting ------------------------------------------------
/** The range currently in effect, incl. the live hover preview while picking. */
const effectiveRange = computed(() => {
  const end = phase.value === 'end' ? hover.value || pendingEnd.value : pendingEnd.value
  const start = pendingStart.value
  if (!start || !end) return { lo: start || null, hi: null }
  return start <= end ? { lo: start, hi: end } : { lo: end, hi: start }
})

function isEndpoint(iso) {
  const { lo, hi } = effectiveRange.value
  return iso === lo || iso === hi
}

/** Wrapper (range-band) classes: the soft action band connecting the endpoints. */
function wrapClass(cell) {
  const { lo, hi } = effectiveRange.value
  if (!lo || !hi || lo === hi) return ''
  if (cell.iso < lo || cell.iso > hi) return ''
  const rounded = cell.iso === lo ? 'rounded-l-full' : cell.iso === hi ? 'rounded-r-full' : ''
  return `bg-action/10 ${rounded}`
}

/** Day-number button classes: solid action endpoints, subtle in-between/hover. */
function btnClass(cell) {
  if (cell.disabled) return 'text-border-subtle cursor-not-allowed'
  if (isEndpoint(cell.iso)) return 'bg-action text-white font-semibold shadow-soft'
  const { lo, hi } = effectiveRange.value
  const inside = lo && hi && cell.iso > lo && cell.iso < hi
  const base = inside ? 'text-action' : cell.inMonth ? 'text-primary' : 'text-muted'
  const todayRing = cell.iso === todayIso ? 'ring-1 ring-inset ring-action/40' : ''
  return `${base} ${todayRing} hover:bg-action/15`
}

// --- interactions ------------------------------------------------------
function openCalendar() {
  // Show the two most recent relevant months (the `to` month + the one before).
  const [y, m] = (props.to || todayIso).split('-').map(Number)
  const d = new Date(y, m - 2, 1) // m is 1-based → left month = to-month − 1
  viewYear.value = d.getFullYear()
  viewMonth.value = d.getMonth()
  pendingStart.value = props.from
  pendingEnd.value = props.to
  phase.value = 'start'
  hover.value = null
  open.value = true
}

function toggle() {
  if (open.value) open.value = false
  else openCalendar()
}

function pickDay(cell) {
  if (cell.disabled) return
  if (phase.value === 'start') {
    pendingStart.value = cell.iso
    pendingEnd.value = null
    phase.value = 'end'
    return
  }
  let [s, e] = [pendingStart.value, cell.iso]
  if (e < s) [s, e] = [e, s]
  pendingStart.value = s
  pendingEnd.value = e
  phase.value = 'start'
  emit('update:from', s)
  emit('update:to', e)
  open.value = false
}

function onHover(cell) {
  if (phase.value === 'end' && !cell.disabled) hover.value = cell.iso
}

function applyPreset(days) {
  const from = isoDaysAgo(days)
  const to = isoDaysAgo(1)
  emit('update:from', from)
  emit('update:to', to)
  open.value = false
}

// --- dismissal ---------------------------------------------------------
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
  <div ref="root" class="relative flex items-center gap-sm">
    <span class="text-tiny font-medium uppercase tracking-wider text-muted">Период</span>

    <!-- Single trigger: the whole range reads as one control. -->
    <button
      type="button"
      class="flex h-9 items-center gap-sm rounded-input border bg-surface px-sm text-base tabular-nums text-primary shadow-soft transition-colors hover:border-action/60"
      :class="open ? 'border-action ring-2 ring-action/20' : 'border-border-subtle'"
      @click="toggle"
    >
      <svg class="h-4 w-4 shrink-0 text-muted" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <rect x="1.75" y="2.75" width="12.5" height="11.5" rx="2" />
        <path d="M1.75 6.25h12.5M5 1.25v3M11 1.25v3" />
      </svg>
      <span>{{ fmt(from) }}</span>
      <span class="text-muted" aria-hidden="true">→</span>
      <span>{{ fmt(to) }}</span>
    </button>

    <!-- Calendar popover -->
    <transition name="cal">
      <div
        v-if="open"
        class="calendar-pop absolute left-0 top-[calc(100%+6px)] z-40 rounded-card border border-border-subtle bg-surface p-md shadow-card backdrop-blur-xl"
        role="dialog"
        aria-label="Выбор периода"
      >
        <!-- Header: navigation + the two month labels -->
        <div class="mb-sm flex items-center">
          <button type="button" class="nav-btn" aria-label="Предыдущий месяц" @click="shiftView(-1)">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M10 3.5 5.5 8l4.5 4.5" /></svg>
          </button>
          <div class="flex flex-1 justify-around px-sm text-base font-semibold text-primary">
            <span v-for="m in monthsToShow" :key="m.label">{{ m.label }}</span>
          </div>
          <button
            type="button"
            class="nav-btn"
            :disabled="!canGoNext"
            aria-label="Следующий месяц"
            @click="shiftView(1)"
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M6 3.5 10.5 8 6 12.5" /></svg>
          </button>
        </div>

        <!-- Two months side by side -->
        <div class="flex flex-col gap-lg sm:flex-row" @mouseleave="hover = null">
          <div v-for="(m, mi) in monthsToShow" :key="mi" class="calendar-grid">
            <div v-for="w in WEEKDAYS" :key="w" class="weekday">{{ w }}</div>
            <div v-for="cell in m.cells" :key="cell.iso" class="day-wrap" :class="wrapClass(cell)">
              <button
                type="button"
                class="day"
                :class="btnClass(cell)"
                :disabled="cell.disabled"
                @click="pickDay(cell)"
                @mouseenter="onHover(cell)"
              >
                {{ cell.day }}
              </button>
            </div>
          </div>
        </div>

        <!-- Footer: quick presets -->
        <div class="mt-md flex items-center gap-xs border-t border-border-subtle pt-sm">
          <span class="mr-auto text-tiny text-muted">
            {{ phase === 'end' ? 'Выберите конец периода' : 'Быстрый выбор:' }}
          </span>
          <button
            v-for="preset in PRESETS"
            :key="preset.days"
            type="button"
            class="preset-btn"
            @click="applyPreset(preset.days)"
          >
            {{ preset.label }}
          </button>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.calendar-pop {
  min-width: 18rem;
}

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

.preset-btn {
  border-radius: 6px;
  border: 1px solid #e0e0e0;
  padding: 3px 10px;
  font-size: 0.75rem; /* tiny */
  font-weight: 500;
  color: #101010;
  transition:
    background-color 0.12s ease,
    border-color 0.12s ease,
    color 0.12s ease;
}
.preset-btn:hover {
  border-color: var(--color-action, #007e76);
  background: color-mix(in srgb, var(--color-action, #007e76) 10%, transparent);
  color: var(--color-action, #007e76);
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
