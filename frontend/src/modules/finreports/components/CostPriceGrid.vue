<script setup>
import { currencyInWords } from '@/core/utils/format'
/**
 * Editable cost-price grid.
 *
 * One number per SKU, entered by hand — so the grid's whole job is to make the
 * *gaps* as visible as the entries. Uncosted SKUs are listed alongside the
 * costed ones, sorted by units settled, because the seller's next-best action is
 * always "cost the SKU that sells most", never "cost the next one alphabetically".
 *
 * Edits are local until saved, and the parent saves the whole grid in one
 * request: a per-row autosave over a financial input means a mistyped digit is
 * persisted before the eye reaches the next column.
 */
import { computed, ref, watch } from 'vue'

import CostPriceRows from '@/modules/finreports/components/CostPriceRows.vue'
import CostPriceTable from '@/modules/finreports/components/CostPriceTable.vue'

const props = defineProps({
  /** @type {Array<object>} Costed SKUs from the backend. */
  items: { type: Array, default: () => [] },
  /** @type {Array<object>} SKUs that have sold but carry no cost. */
  missing: { type: Array, default: () => [] },
  currency: { type: String, default: 'KGS' },
  saving: { type: Boolean, default: false },
})

const emit = defineEmits(['save', 'remove'])

/** Local edit buffer, keyed by nm_id. */
const draft = ref({})

const rows = computed(() => {
  const costed = props.items.map((i) => ({
    nmId: i.nm_id,
    vendorCode: i.vendor_code,
    soldUnits: i.sold_units,
    stored: i.cost,
    currency: i.currency,
    source: i.source,
    note: i.note,
  }))
  const uncosted = props.missing.map((m) => ({
    nmId: m.nm_id,
    vendorCode: m.vendor_code,
    soldUnits: m.sold_units,
    stored: null,
    currency: props.currency,
    source: '',
    note: '',
  }))
  // Uncosted first, by volume: these are the statement's blind spots.
  return [
    ...uncosted.sort((a, b) => b.soldUnits - a.soldUnits),
    ...costed.sort((a, b) => b.soldUnits - a.soldUnits),
  ]
})

/** Reset the buffer whenever the server data is replaced. */
watch(
  () => [props.items, props.missing],
  () => {
    draft.value = {}
  },
)

function value(row) {
  return draft.value[row.nmId] ?? (row.stored === null ? '' : String(row.stored))
}

function onInput(row, raw) {
  draft.value = { ...draft.value, [row.nmId]: raw }
}

/**
 * The costs to write.
 *
 * Two comparisons that look interchangeable and are not:
 *
 * - an uncosted row has `stored === null`, and `Number(null)` is 0 — so comparing
 *   with `Number(row.stored)` makes a legitimately-typed `0` equal to "no cost on
 *   file" and silently drops the edit. Absent must never compare equal to a value.
 * - a *cleared* field is not "no change". Emptying a cost the seller wants gone
 *   and pressing Save has to remove it, or the old figure keeps sitting in every
 *   margin while the grid shows an empty box.
 */
const edits = computed(() => {
  const save = []
  const clear = []
  for (const row of rows.value) {
    const raw = draft.value[row.nmId]
    if (raw === undefined) continue
    if (raw === '') {
      if (row.stored !== null) clear.push(row.nmId)
      continue
    }
    const stored = row.stored === null ? null : Number(row.stored)
    if (stored !== null && Number(raw) === stored) continue
    save.push({
      nm_id: row.nmId,
      cost: Number(raw),
      currency: props.currency,
      vendor_code: row.vendorCode,
    })
  }
  return { save, clear }
})

const pendingCount = computed(() => edits.value.save.length + edits.value.clear.length)

const invalid = computed(() =>
  Object.entries(draft.value).some(
    ([, raw]) => raw !== '' && (!Number.isFinite(Number(raw)) || Number(raw) < 0),
  ),
)
</script>

<template>
  <div>
    <div class="mb-md flex flex-wrap items-center gap-md phone:gap-sm">
      <button
        type="button"
        class="ui-btn ui-btn--primary phone:w-full"
        :disabled="saving || !pendingCount || invalid"
        @click="emit('save', edits)"
      >
        {{ saving ? 'Сохраняем…' : `Сохранить (${pendingCount})` }}
      </button>
      <p v-if="invalid" class="text-base text-status-negative">
        Себестоимость должна быть неотрицательным числом.
      </p>
      <p v-else class="text-tiny text-muted">
        Себестоимость за 1 ед. с фулфилментом, {{ currencyInWords(currency) }}. Применяется ко всей
        истории продаж.
      </p>
    </div>

    <!-- Below `sm` the six columns become one row per SKU, input included — see
         the phone-layout skill for why the switch is at `sm`, not `phone:`.
         Both read the same `rows` and write the same draft buffer. -->
    <CostPriceRows
      class="sm:hidden"
      :rows="rows"
      :value="value"
      :saving="saving"
      @input="onInput"
      @remove="emit('remove', $event)"
    />

    <CostPriceTable
      class="hidden sm:block"
      :rows="rows"
      :value="value"
      :saving="saving"
      @input="onInput"
      @remove="emit('remove', $event)"
    />
  </div>
</template>
