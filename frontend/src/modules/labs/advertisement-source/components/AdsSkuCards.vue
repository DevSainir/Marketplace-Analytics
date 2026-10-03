<script setup>
/**
 * The per-article advertising list below `sm` — the same rows `AdsSkuTable`
 * renders, one two-line record each.
 *
 * «Реклама» leads (the table's question is «где деньги»), with ДРР beside it;
 * orders and revenue are the second line. A list has no headers to click, so
 * it carries its own sort select, grows ten records at a time instead of
 * paging, and puts the «Итого» FIRST — at the bottom of thirty records nobody
 * would reach it.
 */
import { computed, ref, watch } from 'vue'

import { formatMoney, formatNumber, formatSku } from '@/core/utils/format'
import { DRR_ALARM, ratioPct } from '@/modules/labs/advertisement-source/adsFormat'

const props = defineProps({
  rows: { type: Array, required: true },
  totals: { type: Object, required: true },
  currency: { type: String, default: '' },
})

const PAGE = 10

const SORTS = [
  { key: 'ads', label: 'По рекламе' },
  { key: 'drr', label: 'По ДРР' },
  { key: 'revenue', label: 'По выручке' },
  { key: 'orders', label: 'По заказам' },
]

const sortKey = ref('ads')
const shown = ref(PAGE)

// A new filter or grain is a new list — start it from the top again.
watch(
  () => props.rows,
  () => {
    shown.value = PAGE
  },
)

/** Descending; a missing ДРР sinks to the bottom rather than reading as zero. */
const sorted = computed(() =>
  [...props.rows].sort((a, b) => (b[sortKey.value] ?? -Infinity) - (a[sortKey.value] ?? -Infinity)),
)
const visible = computed(() => sorted.value.slice(0, shown.value))

const money = (value) => formatMoney(value, props.currency)
</script>

<template>
  <div class="rounded-card border border-border-subtle bg-surface px-md py-sm shadow-card">
    <select
      v-model="sortKey"
      aria-label="Сортировка"
      class="mb-sm h-11 w-full rounded-input border border-border-subtle bg-surface px-sm text-base text-primary"
    >
      <option v-for="s in SORTS" :key="s.key" :value="s.key">{{ s.label }}</option>
    </select>

    <div class="flex items-baseline justify-between gap-sm border-b border-border-subtle pb-sm">
      <span class="text-base font-semibold text-primary">Итого {{ rows.length }}</span>
      <span class="tabular-nums font-semibold text-primary">
        {{ money(totals.ads) }} · {{ ratioPct(totals.drr) }}
      </span>
    </div>

    <ul class="divide-y divide-border-subtle">
      <li v-for="row in visible" :key="row.label" class="min-h-11 py-sm">
        <div class="flex items-baseline justify-between gap-sm">
          <span class="min-w-0 truncate text-base font-medium text-primary">
            {{ formatSku(row.label) }}<span v-if="row.n" class="text-muted"> · {{ row.n }}</span>
          </span>
          <span class="flex-none tabular-nums font-semibold text-primary">
            {{ money(row.ads) }}
            <span :class="row.drr > DRR_ALARM ? 'text-status-negative' : 'text-muted'">
              · {{ ratioPct(row.drr) }}
            </span>
          </span>
        </div>
        <div class="flex justify-between gap-sm text-tiny tabular-nums text-muted">
          <span>{{ formatNumber(row.orders) }} заказов</span>
          <span>выручка {{ money(row.revenue) }}</span>
        </div>
      </li>
    </ul>

    <button
      v-if="shown < rows.length"
      type="button"
      class="ui-btn ui-btn--ghost mt-sm min-h-11 w-full"
      @click="shown += PAGE"
    >
      Показать ещё
    </button>
  </div>
</template>
