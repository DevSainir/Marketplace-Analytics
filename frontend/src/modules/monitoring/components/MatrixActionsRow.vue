<script setup>
/**
 * The «Действия» row of the metrics table: what the team DID on each day.
 *
 * Always visible under the comments. Per day, three blocks — «Первая РК» /
 * «Вторая РК» (a campaign-type dropdown plus «Бюджет рекламы») and «Меняли
 * цену?» (Повысили/Понизили plus «На сколько»). Every change emits `action`
 * with a PARTIAL patch; the store merges it into the day's stored state and
 * saves the whole day (last write wins).
 *
 * Renders a `<tbody>`: it is a section of the parent's single `<table>`, so
 * each day's cards sit in that day's column and scroll with it.
 */
import { DAY_COLSPAN } from '@/modules/monitoring/metricsMatrix'

const props = defineProps({
  /** @type {Array<{iso: string, label: string}>} oldest -> newest */
  days: { type: Array, required: true },
  /** Persisted «Действия» rows, keyed by ISO day (touched days only). */
  dayActions: { type: Object, default: () => ({}) },
  /** ISO days whose action save is in flight (their controls are disabled). */
  actionSavingDays: { type: Set, default: () => new Set() },
})

const emit = defineEmits(['action'])

const PRICE_CHANGE_OPTIONS = [
  { value: 'up', label: 'Повысили' },
  { value: 'down', label: 'Понизили' },
]

// The campaign types a РК slot can hold. The two slots draw from this same
// list but are kept distinct (a type picked in one is disabled in the other).
const RK_TYPE_OPTIONS = [
  { value: 'uni', label: 'Единая' },
  { value: 'manual_search', label: 'Руч. поиск' },
  { value: 'manual_shelves', label: 'Руч. полки' },
  { value: 'cpc', label: 'CPC' },
]

// The two РК blocks share one markup (v-for over this config). `otherTypeField`
// is the sibling slot, read to sync the dropdowns.
const RK_BLOCKS = [
  {
    typeField: 'first_rk_type',
    budgetField: 'first_rk_budget',
    otherTypeField: 'second_rk_type',
    title: 'Первая РК',
  },
  {
    typeField: 'second_rk_type',
    budgetField: 'second_rk_budget',
    otherTypeField: 'first_rk_type',
    title: 'Вторая РК',
  },
]
/** The day's stored answers (or an all-null blank). */
function dayAction(iso) {
  return props.dayActions[iso] ?? {}
}

/** Whether a type option is already taken by the OTHER РК slot (so, disabled). */
function isTypeTaken(iso, block, optionValue) {
  return dayAction(iso)[block.otherTypeField] === optionValue
}

/** Commit a РК slot's type; clearing it takes its now-locked budget with it. */
function commitRkType(iso, block, event) {
  const next = event.target.value || null
  const patch = { [block.typeField]: next }
  // No type -> the budget is about to lock; a number left behind it could not
  // be read back or cleared, so it goes with the type.
  if (next === null) patch[block.budgetField] = null
  emit('action', { day: iso, patch })
}

/** «Меняли цену?» select: '' un-answers, otherwise up/down. */
function commitPriceChange(iso, event) {
  const next = event.target.value || null
  const patch = { price_change: next }
  // Same rule as the budgets: no direction leaves no size to state.
  if (next === null) patch.price_change_amount = null
  emit('action', { day: iso, patch })
}

/** Commit a money input (budget / «На сколько») on blur or Enter; blank clears. */
function commitActionAmount(iso, field, event) {
  const raw = event.target.value.trim().replace(',', '.')
  const stored = dayAction(iso)[field] ?? null
  const value = raw === '' ? null : Number(raw)
  if (raw !== '' && (Number.isNaN(value) || value < 0)) {
    event.target.value = stored == null ? '' : String(stored)
    return
  }
  if (value === stored) return
  emit('action', { day: iso, patch: { [field]: value } })
}

/**
 * Whether a day's amount input is locked.
 *
 * An amount only means something once the choice above it is made: a budget
 * belongs to a chosen campaign, a size to a chosen price direction. The input
 * stays disabled until that field carries a value.
 *
 * @param {string} iso The day.
 * @param {string} field The choice field the amount belongs to.
 */
function isAmountLocked(iso, field) {
  const answer = dayAction(iso)[field]
  return answer === null || answer === undefined || answer === ''
}

/** The price select's tint follows the picked direction. */
function priceChangeClass(iso) {
  const value = dayAction(iso).price_change
  if (value === 'up') return 'day-action-select--positive'
  if (value === 'down') return 'day-action-select--negative'
  return ''
}
</script>

<template>
  <tbody class="matrix-actions">
    <tr class="matrix-gap" aria-hidden="true">
      <td :colspan="1 + days.length * DAY_COLSPAN"></td>
    </tr>
    <tr>
      <td>
        <span class="text-micro font-semibold uppercase tracking-wide text-muted"> Действия </span>
      </td>
      <td v-for="day in days" :key="day.iso" :colspan="DAY_COLSPAN">
        <div class="day-action-cards">
          <div v-for="block in RK_BLOCKS" :key="block.typeField" class="day-action-card">
            <span class="day-action-question">{{ block.title }}</span>
            <select
              class="day-action-select"
              :value="dayAction(day.iso)[block.typeField] ?? ''"
              :disabled="actionSavingDays.has(day.iso)"
              :aria-label="`${block.title} (${day.label})`"
              @change="commitRkType(day.iso, block, $event)"
            >
              <option value="">—</option>
              <option
                v-for="option in RK_TYPE_OPTIONS"
                :key="option.value"
                :value="option.value"
                :disabled="isTypeTaken(day.iso, block, option.value)"
              >
                {{ option.label }}
              </option>
            </select>
            <label
              class="day-action-amount"
              :class="isAmountLocked(day.iso, block.typeField) && 'day-action-amount--locked'"
            >
              <span>Бюджет рекламы</span>
              <input
                type="text"
                inputmode="decimal"
                :value="dayAction(day.iso)[block.budgetField] ?? ''"
                :disabled="
                  actionSavingDays.has(day.iso) || isAmountLocked(day.iso, block.typeField)
                "
                :title="isAmountLocked(day.iso, block.typeField) ? 'Сначала выберите РК' : null"
                @keydown.enter.prevent="$event.target.blur()"
                @blur="commitActionAmount(day.iso, block.budgetField, $event)"
              />
            </label>
          </div>

          <div class="day-action-card">
            <span class="day-action-question">Меняли цену?</span>
            <select
              class="day-action-select"
              :class="priceChangeClass(day.iso)"
              :value="dayAction(day.iso).price_change ?? ''"
              :disabled="actionSavingDays.has(day.iso)"
              :aria-label="`Меняли цену? (${day.label})`"
              @change="commitPriceChange(day.iso, $event)"
            >
              <option value="">—</option>
              <option
                v-for="option in PRICE_CHANGE_OPTIONS"
                :key="option.value"
                :value="option.value"
              >
                {{ option.label }}
              </option>
            </select>
            <label
              class="day-action-amount"
              :class="isAmountLocked(day.iso, 'price_change') && 'day-action-amount--locked'"
            >
              <span>На сколько</span>
              <input
                type="text"
                inputmode="decimal"
                :value="dayAction(day.iso).price_change_amount ?? ''"
                :disabled="actionSavingDays.has(day.iso) || isAmountLocked(day.iso, 'price_change')"
                :title="
                  isAmountLocked(day.iso, 'price_change') ? 'Сначала ответьте на вопрос' : null
                "
                @keydown.enter.prevent="$event.target.blur()"
                @blur="commitActionAmount(day.iso, 'price_change_amount', $event)"
              />
            </label>
          </div>
        </div>
      </td>
    </tr>
  </tbody>
</template>

<style scoped src="./styles/MatrixActionsRow.css"></style>
