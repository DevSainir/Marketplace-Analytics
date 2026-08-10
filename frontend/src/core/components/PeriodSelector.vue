<script setup>
/**
 * Custom date-range picker: ONE control that opens a single calendar popover.
 *
 * Flow: click the field → the calendar opens → click the start day → click the
 * end day → the popover closes with the range set (the parent still applies it
 * with «Применить»). Between the two clicks, hovering previews the range. Quick
 * presets (7 / 30 / 90 дней) set a rolling window ending on `presetEnd` —
 * today unless the caller names a last day (it counts as one of the N).
 *
 * Lives in `core/`: two modules pick periods with it — monitoring's matrix and
 * the finreports P&L.
 *
 * Fully custom (no native `<input type=date>` — its calendar is off-brand):
 * styled with the design system, action-color endpoints and a soft action
 * range band, on-brand hover/focus. Dates are compared as ISO strings
 * (`YYYY-MM-DD` sorts lexicographically), so no timezone math is needed.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { isoDaysAgo, isoLocalDate } from '@/core/utils/dates'
import { btnClass, effectiveRange, wrapClass } from '@/core/utils/calendarHighlight'
import { PRESETS, TODAY, TODAY_ISO, useCalendarView, WEEKDAYS } from '@/core/utils/calendarModel'

const props = defineProps({
  from: { type: String, required: true },
  to: { type: String, required: true },
  /**
   * Day the quick presets end on (ISO). Empty = today, which is right for live
   * traffic data. The P&L passes its newest SETTLED day instead: WB publishes a
   * settlement week at a time, so «7 дней» ending today would silently include
   * days no report covers yet and read as a collapse in sales.
   */
  presetEnd: { type: String, default: '' },
})
const emit = defineEmits(['update:from', 'update:to'])

// --- popover + view state ----------------------------------------------
const root = ref(null)
const open = ref(false)
const viewYear = ref(TODAY.getFullYear())
const viewMonth = ref(TODAY.getMonth()) // 0-based, the LEFT month of the pair

const { monthsToShow, canGoNext, shiftView } = useCalendarView(viewYear, viewMonth)

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

// --- range highlighting ------------------------------------------------
// Thin adapters over calendarHighlight: the component supplies the live state,
// the module decides the paint.
const range = computed(() =>
  effectiveRange({
    start: pendingStart.value,
    end: pendingEnd.value,
    hover: hover.value,
    phase: phase.value,
  }),
)

const dayWrapClass = (cell) => wrapClass(cell, range.value)
const dayBtnClass = (cell) => btnClass(cell, range.value, TODAY_ISO)

// --- interactions ------------------------------------------------------
function openCalendar() {
  // Show the two most recent relevant months (the `to` month + the one before).
  const [y, m] = (props.to || TODAY_ISO).split('-').map(Number)
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
  const to = props.presetEnd || isoDaysAgo(0)
  const end = new Date(`${to}T00:00:00`)
  const from = isoLocalDate(new Date(end.getTime() - (days - 1) * 86400000))
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
      <svg
        class="h-4 w-4 shrink-0 text-muted"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        aria-hidden="true"
      >
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
        class="calendar-pop absolute left-0 top-[calc(100%+6px)] z-40 rounded-card border border-border-subtle bg-surface p-md shadow-card"
        role="dialog"
        aria-label="Выбор периода"
      >
        <!-- Header: navigation + the two month labels -->
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
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75">
              <path d="M6 3.5 10.5 8 6 12.5" />
            </svg>
          </button>
        </div>

        <!-- Two months side by side -->
        <div class="flex flex-col gap-lg sm:flex-row" @mouseleave="hover = null">
          <div v-for="(m, mi) in monthsToShow" :key="mi" class="calendar-grid">
            <div v-for="w in WEEKDAYS" :key="w" class="weekday">{{ w }}</div>
            <div
              v-for="cell in m.cells"
              :key="cell.iso"
              class="day-wrap"
              :class="dayWrapClass(cell)"
            >
              <button
                type="button"
                class="day"
                :class="dayBtnClass(cell)"
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

<style scoped src="./styles/PeriodSelector.css"></style>
