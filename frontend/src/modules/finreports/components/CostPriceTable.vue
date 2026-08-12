<script setup>
/**
 * The cost-price grid as a table — the desktop projection of `CostPriceGrid`.
 *
 * Six columns per SKU with the cost as an editable cell. Uncosted rows carry a
 * warning tint: the grid's job is to make the *gaps* as visible as the entries,
 * because the seller's next-best action is always «cost the SKU that sells
 * most». Split out of `CostPriceGrid` when the phone row list joined it there.
 *
 * Dumb by contract: the parent owns the draft buffer and the save.
 */
import { formatNumber } from '@/core/utils/format'

defineProps({
  /** @type {Array<object>} Rows from `CostPriceGrid`, uncosted first by volume. */
  rows: { type: Array, default: () => [] },
  /** Reads the current draft (or stored) value of a row. */
  value: { type: Function, required: true },
  saving: { type: Boolean, default: false },
})

const emit = defineEmits(['input', 'remove'])
</script>

<template>
  <div class="overflow-x-auto rounded-card border border-border-subtle bg-surface shadow-card">
    <table class="w-full min-w-[720px] text-base">
      <thead class="border-b border-border-subtle text-left text-tiny uppercase text-muted">
        <tr>
          <th class="px-md py-sm">Артикул</th>
          <th class="px-md py-sm">nm_id</th>
          <th class="px-md py-sm text-right">Продано, шт</th>
          <th class="px-md py-sm text-right">Себестоимость</th>
          <th class="px-md py-sm">Источник</th>
          <th class="px-md py-sm"></th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="row.nmId"
          class="border-b border-border-subtle/60 last:border-0"
          :class="row.stored === null ? 'bg-status-warning/5' : ''"
        >
          <td class="px-md py-sm font-medium text-primary">{{ row.vendorCode || '—' }}</td>
          <td class="px-md py-sm tabular-nums text-muted">{{ row.nmId }}</td>
          <td class="px-md py-sm text-right tabular-nums text-primary">
            {{ formatNumber(row.soldUnits) }}
          </td>
          <td class="px-md py-sm text-right">
            <input
              type="number"
              min="0"
              step="1"
              inputmode="decimal"
              class="w-28 rounded-input border border-border-subtle bg-canvas px-sm py-xs text-right tabular-nums text-primary focus:border-action focus:outline-none"
              :value="value(row)"
              :placeholder="row.stored === null ? 'не задана' : ''"
              @input="emit('input', row, $event.target.value)"
            />
          </td>
          <td class="px-md py-sm text-tiny text-muted">
            {{
              row.source === 'seed' ? 'со слов продавца' : row.source === 'manual' ? 'вручную' : '—'
            }}
          </td>
          <td class="px-md py-sm text-right">
            <button
              v-if="row.stored !== null"
              type="button"
              class="rounded-btn px-sm py-xs text-tiny font-medium text-muted transition hover:bg-status-negative/10 hover:text-status-negative"
              :disabled="saving"
              @click="emit('remove', row.nmId)"
            >
              Очистить
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="6" class="px-md py-xl text-center text-muted">
            Нет проданных SKU за последний год.
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
