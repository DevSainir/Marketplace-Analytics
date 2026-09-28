<script setup>
/**
 * The heatmap on a phone: one column at a time, as a list.
 *
 * A grid of articles × days has no «record» to fold into a card, and swiping a
 * thirty-column table sideways loses the row the reader was on — the same
 * finding that made the monitoring matrix page its day axis. So the columns
 * are paged instead (`‹ 23.09 (ср) ›`) and each article is one line: its name,
 * the painted value for that column, and its «Итого» for the window. The
 * «Итого» line comes first, as the phone recipe asks.
 *
 * The same rows and tints the desktop grid draws — one source, two projections.
 */
import { computed, ref, watch } from 'vue'

import SkuThumb from '@/core/components/SkuThumb.vue'
import { formatSku } from '@/core/utils/format'
import { columnLabel } from '@/modules/heatmap/grid'
import { formatValue } from '@/modules/heatmap/metrics'

const props = defineProps({
  columns: { type: Array, required: true },
  period: { type: String, required: true },
  rows: { type: Array, required: true },
  tints: { type: Array, required: true },
  totals: { type: Object, default: null },
  primary: { type: Object, required: true },
  secondary: { type: Object, default: null },
})

// Columns run oldest first; a phone opens on the newest one.
const index = ref(Math.max(props.columns.length - 1, 0))
watch(
  () => props.columns,
  (columns) => (index.value = Math.max(columns.length - 1, 0)),
)

const column = computed(() => props.columns[index.value] ?? null)
const top = (value) => formatValue(value, props.primary.unit)
const bottom = (value) => formatValue(value, props.secondary?.unit ?? 'count')
</script>

<template>
  <div v-if="column">
    <div class="mb-sm flex items-center justify-between gap-sm">
      <button
        type="button"
        class="hm-trigger hm-trigger--icon"
        :disabled="index <= 0"
        aria-label="Раньше"
        @click="index -= 1"
      >
        ‹
      </button>
      <span class="text-base font-semibold text-primary">{{ columnLabel(column, period) }}</span>
      <button
        type="button"
        class="hm-trigger hm-trigger--icon"
        :disabled="index >= columns.length - 1"
        aria-label="Позже"
        @click="index += 1"
      >
        ›
      </button>
    </div>

    <ul class="divide-y divide-border-subtle rounded-card bg-surface shadow-card">
      <li v-if="totals" class="flex items-center gap-sm bg-canvas px-md py-sm font-semibold">
        <span class="flex-1">Итого</span>
        <span class="text-right">
          <span class="block">{{ top(totals.values[index]) }}</span>
          <span v-if="secondary" class="block text-tiny text-muted">{{
            bottom(totals.values2[index])
          }}</span>
        </span>
      </li>
      <li
        v-for="(row, rowIndex) in rows"
        :key="row.key"
        class="flex items-center gap-sm px-md py-sm"
      >
        <SkuThumb v-if="row.nm_id" :src="row.photo_url" :label="row.label" />
        <span class="min-w-0 flex-1">
          <span class="block truncate text-base text-primary">
            {{ row.nm_id ? formatSku(row.label) : row.label }}
          </span>
          <span class="block text-tiny text-muted">Итого: {{ top(row.total) }}</span>
        </span>
        <span
          class="min-w-20 rounded-btn px-sm py-xs text-right tabular-nums"
          :style="{ background: tints[rowIndex]?.[index] || undefined }"
        >
          <span class="block text-base text-primary">{{ top(row.values[index]) }}</span>
          <span v-if="secondary" class="block text-tiny text-muted">{{
            bottom(row.values2[index])
          }}</span>
        </span>
      </li>
    </ul>
  </div>
</template>
