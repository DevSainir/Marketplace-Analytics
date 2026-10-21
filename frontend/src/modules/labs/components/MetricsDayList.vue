<script setup>
/**
 * The metrics matrix on a phone: ONE day at a time, as a vertical list.
 *
 * The sibling of `MetricsTable` below the `sm` breakpoint — see
 * `dayListRows.js` for why the table itself cannot be narrowed this far. A
 * pager moves between days, each metric is a row of `label · value`, and the
 * traffic split hides behind a per-metric disclosure so the list stays a list.
 *
 * Editing works the same way it does in the table (click the value, Enter or
 * blur to commit) but only on the headline «Общая» cell: it is the number
 * anyone corrects from a phone, and 8 tap targets per metric would bury it.
 * The per-zone values stay read-only here; the desktop table is where a split
 * gets edited.
 */
import { computed, ref, watch } from 'vue'

import DayActionsForm from '@/modules/labs/components/DayActionsForm.vue'
import DayNoteForm from '@/modules/labs/components/DayNoteForm.vue'
import { blockDayItems, dayLabelWithWeekday, metricDayItems } from '@/modules/labs/dayListRows'
import { useCellEditing, vFocus } from '@/modules/labs/useCellEditing'

const props = defineProps({
  /** @type {Array<{iso: string, label: string}>} oldest → newest */
  days: { type: Array, required: true },
  /** @type {Array<{key, label, tone, cells: object[]}>} day-major cell objects */
  rows: { type: Array, required: true },
  priceRows: { type: Array, default: () => [] },
  stockRows: { type: Array, default: () => [] },
  stockTotalRows: { type: Array, default: () => [] },
  editingDisabled: { type: Boolean, default: false },
  /** Persisted day notes, keyed by ISO day: `{body, header}` per commented day. */
  comments: { type: Object, default: () => ({}) },
  /** ISO days whose note save is in flight. */
  commentSavingDays: { type: Set, default: () => new Set() },
  /** Persisted «Действия» rows, keyed by ISO day (touched days only). */
  dayActions: { type: Object, default: () => ({}) },
  /** ISO days whose action save is in flight. */
  actionSavingDays: { type: Set, default: () => new Set() },
})

const emit = defineEmits(['edit', 'comment', 'action'])

/** Open on «сегодня», the same day the table scrolls itself to. */
const dayIndex = ref(props.days.length - 1)
watch(
  () => props.days,
  (days) => {
    dayIndex.value = days.length - 1
  },
)

const day = computed(() => props.days[dayIndex.value] ?? null)
const dayLabel = computed(() => dayLabelWithWeekday(day.value))

function step(delta) {
  const next = dayIndex.value + delta
  if (next < 0 || next > props.days.length - 1) return
  dayIndex.value = next
  expanded.value = new Set()
}

const sections = computed(() => [
  { key: 'metrics', title: null, items: metricDayItems(props.rows, dayIndex.value) },
  { key: 'prices', title: 'Цены', items: blockDayItems(props.priceRows, dayIndex.value) },
  {
    key: 'stock',
    title: 'Остатки',
    items: blockDayItems([...props.stockRows, ...props.stockTotalRows], dayIndex.value),
  },
])

const note = computed(() => props.comments[day.value?.iso] ?? { header: '', body: '' })
const action = computed(() => props.dayActions[day.value?.iso] ?? {})

const expanded = ref(new Set())

function toggle(key) {
  const next = new Set(expanded.value)
  if (!next.delete(key)) next.add(key)
  expanded.value = next
}

const { editingId, cellId, draft, startEdit, commitEdit, cancelEdit } = useCellEditing({
  disabled: () => props.editingDisabled,
  onCommit: (payload) => emit('edit', payload),
})

// Same metric accents as the table.
const TONE_CLASSES = {
  warning: 'text-status-warning',
  negative: 'text-status-negative',
  positive: 'text-status-positive',
  carts: 'text-accent-indigo',
}

/**
 * Blank cells render as «—» here, where the table leaves them empty: a dash is
 * noise across a mostly-empty ribbon, but a blank row in a vertical list reads
 * as a rendering fault rather than as "no data".
 */
function valueText(cell) {
  return cell?.display || '—'
}
</script>

<template>
  <div>
    <!-- Day pager: the list's only navigation, so it stays put above the
         scroll rather than riding with it. -->
    <div class="flex items-center justify-between gap-sm">
      <button
        type="button"
        class="day-step"
        :disabled="dayIndex <= 0"
        aria-label="Предыдущий день"
        @click="step(-1)"
      >
        ‹
      </button>

      <p class="text-h3 font-semibold tabular-nums text-primary">{{ dayLabel }}</p>

      <button
        type="button"
        class="day-step"
        :disabled="dayIndex >= days.length - 1"
        aria-label="Следующий день"
        @click="step(1)"
      >
        ›
      </button>
    </div>

    <p v-if="!rows.length" class="mt-lg text-center text-base text-muted">
      Нет данных за выбранный период.
    </p>

    <template v-else>
      <section v-for="section in sections" :key="section.key" class="mt-md">
        <h3 v-if="section.title" class="mb-xs text-tiny font-medium uppercase text-muted">
          {{ section.title }}
        </h3>

        <ul class="day-list">
          <li v-for="item in section.items" :key="item.key">
            <div class="day-row" :class="item.emphasis && 'font-bold'">
              <span
                class="min-w-0 flex-1"
                :class="item.tone ? TONE_CLASSES[item.tone] : 'text-primary'"
              >
                {{ item.label }}
              </span>

              <input
                v-if="item.cell && editingId === cellId(item.key, item.cell)"
                v-model="draft"
                v-focus
                type="text"
                inputmode="decimal"
                class="day-value-input"
                @keydown.enter.prevent="commitEdit(item, item.cell)"
                @keydown.esc.prevent="cancelEdit"
                @blur="commitEdit(item, item.cell)"
              />
              <button
                v-else-if="item.cell?.editable && !editingDisabled"
                type="button"
                class="day-value day-value--editable"
                :class="item.tone && item.cell.raw != null ? TONE_CLASSES[item.tone] : ''"
                @click="startEdit(item, item.cell)"
              >
                {{ valueText(item.cell) }}
              </button>
              <span
                v-else
                class="day-value"
                :class="item.tone && item.cell?.raw != null ? TONE_CLASSES[item.tone] : ''"
              >
                {{ valueText(item.cell) }}
              </span>

              <button
                v-if="item.breakdown"
                type="button"
                class="day-disclosure"
                :aria-expanded="expanded.has(item.key)"
                :aria-label="`Детализация по трафику: ${item.label}`"
                @click="toggle(item.key)"
              >
                <svg
                  class="h-4 w-4 transition"
                  :class="expanded.has(item.key) && 'rotate-180'"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path d="m6 9 6 6 6-6" />
                </svg>
              </button>
            </div>

            <ul v-if="item.breakdown && expanded.has(item.key)" class="day-breakdown">
              <li v-for="entry in item.breakdown" :key="entry.label" class="day-breakdown-row">
                <span class="min-w-0 flex-1 truncate">{{ entry.label }}</span>
                <span class="tabular-nums">{{ valueText(entry.cell) }}</span>
              </li>
            </ul>
          </li>
        </ul>
      </section>

      <!-- The day's own record: what was noted and what was done. Both belong to
           the day the pager is on, like every section above them. -->
      <DayNoteForm
        v-if="day"
        :day="day"
        :note="note"
        :saving="commentSavingDays.has(day.iso)"
        @comment="emit('comment', $event)"
      />
      <DayActionsForm
        v-if="day"
        :day="day"
        :action="action"
        :saving="actionSavingDays.has(day.iso)"
        @action="emit('action', $event)"
      />
    </template>
  </div>
</template>

<style scoped src="./styles/MetricsDayList.css"></style>
