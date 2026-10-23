<script setup>
/**
 * "Cost price" for one article, asked from the P&L row that lacks it.
 *
 * A dialog rather than a field in the cell: the table re-renders a cell on a
 * row click (see `PnlPenaltyReasons`) and an input there would lose its text,
 * and on a phone a popover anchored to a row is closed by the very scroll the
 * on-screen keyboard causes. The dialog is the same on both projections.
 *
 * It only collects and checks the figure; writing it is the `save` function
 * the page hands down, so this stays a component without a request in it.
 * The bounds mirror the backend's (`CostPriceInput`): not negative, and not
 * past the typo guard that catches a five-digit slip.
 */
import { computed, nextTick, ref, watch } from 'vue'

import UiDialog from '@/core/components/UiDialog.vue'
import { extractErrorMessage } from '@/core/api/axios'
import { currencyInWords, formatNumber, normalizeTypedNumber } from '@/core/utils/format'

/** `MAX_UNIT_COST` in `backend/.../schemas/cost_price.py`. */
const MAX_COST = 10_000_000

const props = defineProps({
  /** @type {object|null} The flat article row being costed; `null` = closed. */
  row: { type: Object, default: null },
  currency: { type: String, default: '' },
  /** @type {(entry: {nmId: number, cost: number, vendorCode: string}) => Promise<void>} */
  save: { type: Function, required: true },
})

const emit = defineEmits(['close'])

const raw = ref('')
const busy = ref(false)
const error = ref('')
const input = ref(null)

watch(
  () => props.row,
  async (row) => {
    raw.value = ''
    error.value = ''
    if (!row) return
    await nextTick()
    input.value?.focus()
  },
)

/** "1,200", "1 200" and "795,50" are how a seller types a price; all are numbers. */
const cost = computed(() => {
  const text = normalizeTypedNumber(raw.value)
  return text === '' ? null : Number(text)
})
const invalid = computed(
  () =>
    cost.value !== null &&
    (!Number.isFinite(cost.value) || cost.value < 0 || cost.value > MAX_COST),
)

async function submit() {
  if (busy.value || cost.value === null || invalid.value) return
  busy.value = true
  error.value = ''
  try {
    await props.save({ nmId: props.row.nmId, cost: cost.value, vendorCode: props.row.vendorCode })
    emit('close')
  } catch (failure) {
    error.value = extractErrorMessage(failure)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <UiDialog
    :open="!!row"
    title="Cost price"
    :subtitle="row ? `${row.saName} · ${row.nmId}` : ''"
    :busy="busy"
    data-testid="cost-dialog"
    @close="emit('close')"
  >
    <form v-if="row" id="pnl-cost-form" @submit.prevent="submit">
      <label class="block text-tiny font-medium text-muted" for="pnl-cost-input">
        Per unit, fulfillment included, {{ currencyInWords(currency) }}
      </label>
      <input
        id="pnl-cost-input"
        ref="input"
        v-model="raw"
        type="text"
        inputmode="decimal"
        autocomplete="off"
        class="ui-input mt-xs w-full"
        :aria-invalid="invalid"
      />
      <p v-if="invalid" class="mt-xs text-tiny text-status-negative">
        A number from 0 to {{ formatNumber(MAX_COST) }}.
      </p>
      <p v-else-if="error" class="mt-xs text-tiny text-status-negative">{{ error }}</p>
      <p class="mt-sm text-tiny text-muted">
        Sold in the period: {{ formatNumber(row.sold) }} units. The cost price applies to all sales
        history, and profit is recalculated.
      </p>
    </form>

    <template #footer>
      <button type="button" class="ui-btn" :disabled="busy" @click="emit('close')">Cancel</button>
      <button
        type="submit"
        form="pnl-cost-form"
        class="ui-btn ui-btn--primary"
        :disabled="busy || cost === null || invalid"
      >
        {{ busy ? 'Saving…' : 'Save' }}
      </button>
    </template>
  </UiDialog>
</template>
