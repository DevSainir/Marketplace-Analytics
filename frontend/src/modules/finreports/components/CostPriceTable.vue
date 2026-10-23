<script setup>
/**
 * The cost-price grid as a table — the desktop projection of `CostPriceGrid`.
 *
 * Six columns per SKU with the cost as an editable cell. Uncosted rows carry a
 * warning tint: the grid's job is to make the *gaps* as visible as the entries,
 * because the seller's next-best action is always "cost the SKU that sells
 * most". Split out of `CostPriceGrid` when the phone row list joined it there.
 *
 * Dumb by contract: the parent owns the draft buffer and the save.
 */
import { formatNumber, formatSku } from '@/core/utils/format'
import DataState from '@/core/components/DataState.vue'
import { confirmLabel, useConfirmClick } from '@/core/utils/confirmClick'

defineProps({
  /** @type {Array<object>} Rows from `CostPriceGrid`, uncosted first by volume. */
  rows: { type: Array, default: () => [] },
  /** Reads the current draft (or stored) value of a row. */
  value: { type: Function, required: true },
  saving: { type: Boolean, default: false },
})

const emit = defineEmits(['input', 'remove'])

/** Clearing a cost restates every margin on file: asked first (`confirmClick`). */
const clearing = useConfirmClick()
</script>

<template>
  <div class="app-datatable">
    <div class="overflow-x-auto">
      <table class="min-w-[720px]">
        <thead>
          <tr>
            <th>SKU</th>
            <th>WB ID</th>
            <th class="text-right">Sold, units</th>
            <th class="text-right">Cost price</th>
            <th>Source</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.nmId"
            class="border-b border-border-subtle/60 last:border-0"
            :class="row.stored === null ? 'bg-status-warning/5' : ''"
          >
            <td class="font-medium text-primary">
              {{ formatSku(row.vendorCode) || '—' }}
            </td>
            <td class="tabular-nums text-muted">{{ row.nmId }}</td>
            <td class="text-right tabular-nums text-primary">
              {{ formatNumber(row.soldUnits) }}
            </td>
            <td class="text-right">
              <input
                type="number"
                min="0"
                step="1"
                inputmode="decimal"
                class="ui-input ui-input--sm w-28 text-right tabular-nums"
                :value="value(row)"
                :placeholder="row.stored === null ? 'not set' : ''"
                @input="emit('input', row, $event.target.value)"
              />
            </td>
            <td class="text-tiny text-muted">
              {{
                row.source === 'seed' ? 'from the seller' : row.source === 'manual' ? 'manual' : '—'
              }}
            </td>
            <td class="text-right">
              <button
                v-if="row.stored !== null"
                type="button"
                class="ui-btn ui-btn--danger ui-btn--sm"
                :class="{ 'is-armed': clearing.isArmed(row.nmId) }"
                :disabled="saving"
                @click="clearing.press(row.nmId, () => emit('remove', row.nmId))"
              >
                {{ clearing.isArmed(row.nmId) ? confirmLabel('Clear') : 'Clear' }}
              </button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="6">
              <DataState kind="empty" layout="bare" text="No SKUs sold in the last year." />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
