<script setup>
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'

import { formatNumber } from '@/core/utils/format'

/**
 * Multi-size breakdown: one row per size (`chrt_id`) × warehouse cell,
 * mirroring the backend `StockDetail.cells` payload.
 *
 * When the backend provides a human size label (`tech_size` from the WB
 * content-cards dimension) it is shown; otherwise we fall back to the raw
 * `chrt_id` so the table keeps working with the current API.
 */
defineProps({
  cells: { type: Array, required: true },
  bySize: { type: Array, required: true },
})

function sizeLabel(row) {
  return row.tech_size ?? `chrt ${row.chrt_id}`
}
</script>

<template>
  <div class="space-y-3">
    <!-- Per-size rollup chips -->
    <div v-if="bySize.length" class="flex flex-wrap gap-2">
      <span
        v-for="size in bySize"
        :key="size.chrt_id"
        class="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium shadow-sm"
        :class="size.quantity === 0 ? 'text-amber-500' : 'text-slate-700'"
      >
        <span class="text-slate-400">размер</span> {{ sizeLabel(size) }}
        <span class="font-semibold tabular-nums">{{ formatNumber(size.quantity) }}</span>
      </span>
    </div>

    <div class="app-datatable">
      <DataTable :value="cells" :paginator="cells.length > 10" :rows="10" sort-mode="single">
        <template #empty>
          <div class="px-4 py-10 text-center text-sm text-slate-400">
            Нет складских остатков по этому SKU.
          </div>
        </template>

        <Column field="chrt_id" header="Размер" sortable>
          <template #body="{ data }">
            <span class="font-medium text-slate-900">{{ sizeLabel(data) }}</span>
          </template>
        </Column>

        <Column field="warehouse_name" header="Склад" sortable />
        <Column field="region_name" header="Регион" sortable />

        <Column field="quantity" header="Остаток" sortable>
          <template #body="{ data }">
            <span
              class="font-semibold tabular-nums"
              :class="data.quantity === 0 ? 'text-amber-500' : 'text-emerald-500'"
            >
              {{ formatNumber(data.quantity) }}
            </span>
          </template>
        </Column>

        <Column field="in_way_to_client" header="→ К клиенту" sortable>
          <template #body="{ data }">{{ formatNumber(data.in_way_to_client) }}</template>
        </Column>

        <Column field="in_way_from_client" header="← Возвраты" sortable>
          <template #body="{ data }">{{ formatNumber(data.in_way_from_client) }}</template>
        </Column>
      </DataTable>
    </div>
  </div>
</template>
