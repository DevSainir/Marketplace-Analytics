<script setup>
/**
 * The app's one date-range picker: a trigger that opens a calendar, with the
 * quick presets in its footer. Every page that picks a period uses this, and
 * none draws presets of its own — two rows of presets for one window is how a
 * page came to light two of them at once.
 *
 * Flow: click the field → the calendar opens → click the start day → click the
 * end day → the popover closes, the range is set AND applied; between the two,
 * hovering previews. The second click is the whole decision, the same way a
 * preset is, so it does not wait for a button: the popover closing with nothing
 * happening read as a control that had not worked.
 *
 * A page states its bounds and the calendar enforces them by greying days out,
 * rather than the page refusing a window after it was picked:
 * `historyFrom` — the first day it holds data for (also turns «180 дней» into
 * «Вся история»); `max` — the last pickable day; `maxDays` — the longest window
 * it answers for, enforced once the first end is clicked.
 *
 * Dates compare as ISO strings, so no timezone math is needed.
 */
import { computed, ref } from 'vue'

import CalendarMonthGrid from '@/core/components/CalendarMonthGrid.vue'
import CalendarShell from '@/core/components/CalendarShell.vue'
import PeriodPresets from '@/core/components/PeriodPresets.vue'
import { btnClass, effectiveRange, wrapClass } from '@/core/utils/calendarHighlight'
import {
  TODAY,
  TODAY_ISO,
  formatDay,
  pickableSpan,
  useCalendarView,
} from '@/core/utils/calendarModel'
import { useMediaQuery } from '@/core/utils/mediaQuery'

const props = defineProps({
  from: { type: String, required: true },
  to: { type: String, required: true },
  /** Day the quick presets end on (ISO); empty = today. See `presetRange`. */
  presetEnd: { type: String, default: '' },
  /** The page's first day with data (ISO): the floor, and «Вся история». Empty = neither. */
  historyFrom: { type: String, default: '' },
  /** Last pickable day (ISO); empty = today. */
  max: { type: String, default: '' },
  /** Longest window the page answers for, both ends counted; 0 = no limit. */
  maxDays: { type: Number, default: 0 },
  label: { type: String, default: 'Период' },
})
/**
 * `update:from` / `update:to` keep `v-model:from` / `v-model:to` working for
 * consumers that only mirror the pair into refs. `range` carries BOTH halves in
 * one event, and a consumer that RELOADS on a change must use it: the two
 * v-model events fire in the same tick, so a listener reading the other half
 * from props sees the value before this pick — which is how a hand-picked
 * period could set only its end and report «Конец периода раньше начала».
 */
const emit = defineEmits(['update:from', 'update:to', 'apply', 'range'])

const open = ref(false)
const viewYear = ref(TODAY.getFullYear())
const viewMonth = ref(TODAY.getMonth())

// `phase` is 'start' until the first click of a new range, then 'end'.
const pendingStart = ref(props.from)
const pendingEnd = ref(props.to)
const phase = ref('start')
const hover = ref(null)

/** Two months need ~560px side by side; below that, one. */
const narrow = useMediaQuery('(max-width: 639px)')

const span = () =>
  pickableSpan({
    min: props.historyFrom,
    max: props.max,
    anchor: phase.value === 'end' ? pendingStart.value : null,
    maxDays: props.maxDays,
  })

const { monthsToShow, canGoNext, canGoPrev, shiftView, showEndingAt } = useCalendarView(
  viewYear,
  viewMonth,
  { count: () => (narrow.value ? 1 : 2), span },
)

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

function onOpening() {
  showEndingAt(props.to)
  pendingStart.value = props.from
  pendingEnd.value = props.to
  phase.value = 'start'
  hover.value = null
}

function commit(from, to) {
  emit('update:from', from)
  emit('update:to', to)
  emit('range', { from, to })
  // Last: a listener that reads the parent's refs rather than the event has to
  // see the new window by the time it runs.
  emit('apply')
  open.value = false
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
  commit(s, e)
}

function onHover(cell) {
  if (phase.value === 'end' && !cell.disabled) hover.value = cell.iso
}
</script>

<template>
  <CalendarShell
    v-model:open="open"
    :label="label"
    aria-label="Выбор периода"
    :titles="monthsToShow.map((m) => m.label)"
    :can-go-prev="canGoPrev"
    :can-go-next="canGoNext"
    @opening="onOpening"
    @shift="shiftView"
  >
    <template #trigger>
      <span>{{ formatDay(from) }}</span>
      <span class="text-muted" aria-hidden="true">→</span>
      <span>{{ formatDay(to) }}</span>
    </template>

    <div class="flex gap-lg" @mouseleave="hover = null">
      <CalendarMonthGrid
        v-for="(m, mi) in monthsToShow"
        :key="mi"
        :cells="m.cells"
        :wrap-class="dayWrapClass"
        :day-class="dayBtnClass"
        @day-click="pickDay"
        @day-hover="onHover"
      />
    </div>

    <template #footer>
      <PeriodPresets
        :from="from"
        :to="to"
        :awaiting-end="phase === 'end'"
        :preset-end="presetEnd"
        :history-from="historyFrom"
        :max-days="maxDays"
        @pick="commit($event.from, $event.to)"
      />
    </template>
  </CalendarShell>
</template>
