<script setup>
/**
 * What the team DID on the day, on a phone — the `MatrixActionsRow` of the day
 * list.
 *
 * Three blocks: «Первая РК» / «Вторая РК» (a campaign type plus its budget) and
 * «Меняли цену?» (direction plus size). Every change emits a PARTIAL patch; the
 * store merges it into the day's stored answers and saves the whole day.
 *
 * The rules that make the form honest, all carried over from the table row
 * because they are about the data, not the layout:
 *
 *   - the two ad campaign slots cannot hold the same campaign type, so each disables the
 *     other's pick;
 *   - clearing a type takes its budget with it — a number behind no campaign
 *     could not be read back or cleared;
 *   - an amount is locked until the choice above it is made: a budget belongs to
 *     a chosen campaign, a size to a chosen direction;
 *   - an amount commits on blur, rejects a negative, and skips a no-op.
 */
const props = defineProps({
  /** @type {{iso: string, label: string}} The day on screen. */
  day: { type: Object, required: true },
  /** @type {object} The day's stored answers, or an all-null blank. */
  action: { type: Object, default: () => ({}) },
  /** True while this day's answers are being saved. */
  saving: { type: Boolean, default: false },
})

const emit = defineEmits(['action'])

const PRICE_CHANGE_OPTIONS = [
  { value: 'up', label: 'Повысили' },
  { value: 'down', label: 'Понизили' },
]

// The campaign types an ad campaign slot can hold. Both slots draw from this list but stay
// distinct — a type picked in one is disabled in the other.
const RK_TYPE_OPTIONS = [
  { value: 'uni', label: 'Единая' },
  { value: 'manual_search', label: 'Руч. поиск' },
  { value: 'manual_shelves', label: 'Руч. полки' },
  { value: 'cpc', label: 'CPC' },
]

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

/** Whether a type option is already taken by the OTHER campaign slot (so, disabled). */
function isTypeTaken(block, optionValue) {
  return props.action[block.otherTypeField] === optionValue
}

/** Commit a campaign slot's type; clearing it takes its now-locked budget with it. */
function commitRkType(block, event) {
  const next = event.target.value || null
  const patch = { [block.typeField]: next }
  if (next === null) patch[block.budgetField] = null
  emit('action', { day: props.day.iso, patch })
}

/** «Меняли цену?»: '' un-answers, otherwise up/down. */
function commitPriceChange(event) {
  const next = event.target.value || null
  const patch = { price_change: next }
  if (next === null) patch.price_change_amount = null
  emit('action', { day: props.day.iso, patch })
}

/** Commit an amount (budget / «На сколько») on blur or Enter; blank clears. */
function commitAmount(field, event) {
  const raw = event.target.value.trim().replace(',', '.')
  const stored = props.action[field] ?? null
  const value = raw === '' ? null : Number(raw)
  if (raw !== '' && (Number.isNaN(value) || value < 0)) {
    event.target.value = stored == null ? '' : String(stored)
    return
  }
  if (value === stored) return
  emit('action', { day: props.day.iso, patch: { [field]: value } })
}

/** An amount only means something once the choice above it is made. */
function isLocked(field) {
  const answer = props.action[field]
  return answer === null || answer === undefined || answer === ''
}

/** The price select's tint follows the picked direction. */
function priceChangeClass() {
  if (props.action.price_change === 'up') return 'text-status-positive'
  if (props.action.price_change === 'down') return 'text-status-negative'
  return ''
}
</script>

<template>
  <section class="mt-md">
    <h3 class="mb-xs text-tiny font-medium uppercase text-muted">Действия</h3>

    <div class="flex flex-col gap-sm">
      <div v-for="block in RK_BLOCKS" :key="block.typeField" class="day-action">
        <label class="day-action-label" :for="`${block.typeField}-${day.iso}`">
          {{ block.title }}
        </label>
        <select
          :id="`${block.typeField}-${day.iso}`"
          class="day-action-control"
          :value="action[block.typeField] ?? ''"
          :disabled="saving"
          @change="commitRkType(block, $event)"
        >
          <option value="">—</option>
          <option
            v-for="option in RK_TYPE_OPTIONS"
            :key="option.value"
            :value="option.value"
            :disabled="isTypeTaken(block, option.value)"
          >
            {{ option.label }}
          </option>
        </select>

        <label class="day-action-label" :for="`${block.budgetField}-${day.iso}`">
          Бюджет рекламы
        </label>
        <input
          :id="`${block.budgetField}-${day.iso}`"
          type="text"
          inputmode="decimal"
          class="day-action-control text-right tabular-nums"
          :value="action[block.budgetField] ?? ''"
          :disabled="saving || isLocked(block.typeField)"
          :title="isLocked(block.typeField) ? 'Сначала выберите РК' : null"
          @keydown.enter.prevent="$event.target.blur()"
          @blur="commitAmount(block.budgetField, $event)"
        />
      </div>

      <div class="day-action">
        <label class="day-action-label" :for="`price-change-${day.iso}`">Меняли цену?</label>
        <select
          :id="`price-change-${day.iso}`"
          class="day-action-control"
          :class="priceChangeClass()"
          :value="action.price_change ?? ''"
          :disabled="saving"
          @change="commitPriceChange($event)"
        >
          <option value="">—</option>
          <option v-for="option in PRICE_CHANGE_OPTIONS" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>

        <label class="day-action-label" :for="`price-amount-${day.iso}`">На сколько</label>
        <input
          :id="`price-amount-${day.iso}`"
          type="text"
          inputmode="decimal"
          class="day-action-control text-right tabular-nums"
          :value="action.price_change_amount ?? ''"
          :disabled="saving || isLocked('price_change')"
          :title="isLocked('price_change') ? 'Сначала ответьте на вопрос' : null"
          @keydown.enter.prevent="$event.target.blur()"
          @blur="commitAmount('price_change_amount', $event)"
        />
      </div>
    </div>
  </section>
</template>

<style scoped>
/* A label/control pair per line, the label given just enough room to read.
   `grid` rather than flex so both rows of a block share one column edge. */
.day-action {
  @apply grid grid-cols-[minmax(0,1fr)_9rem] items-center gap-x-sm gap-y-xs rounded-input bg-canvas px-md py-sm;
}

.day-action-label {
  @apply min-w-0 truncate text-base text-muted;
}

.day-action-control {
  @apply h-11 w-full rounded-input border border-border-subtle bg-surface px-sm text-base text-primary focus:border-action focus:outline-none disabled:cursor-not-allowed disabled:opacity-50;
}
</style>
