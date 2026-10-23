<script setup>
/**
 * The heatmap on a phone: one column at a time, as a list.
 *
 * A grid of articles × days has no "record" to fold into a card, and swiping a
 * thirty-column table sideways loses the row the reader was on — the same
 * finding that made the monitoring matrix page its day axis. So the columns
 * are paged instead (`‹ Wed 23 Sep ›`) and each article is one line: its name,
 * the painted value for that column, and its "Total" for the window. The
 * "Total" line comes first, as the phone recipe asks.
 *
 * The same rows and tints the desktop grid draws — one source, two projections.
 * With "Target: manual" each article line carries its norm field too.
 */
import { computed, ref, watch } from 'vue'

import DataState from '@/core/components/DataState.vue'
import SkuThumb from '@/core/components/SkuThumb.vue'
import HeatmapNormInput from '@/modules/heatmap/components/HeatmapNormInput.vue'
import { formatSku } from '@/core/utils/format'
import { columnLabel } from '@/modules/heatmap/grid'
import { addsUp, cellText } from '@/modules/heatmap/metrics'

const props = defineProps({
  columns: { type: Array, required: true },
  period: { type: String, required: true },
  rows: { type: Array, required: true },
  tints: { type: Array, required: true },
  totals: { type: Object, default: null },
  primary: { type: Object, required: true },
  secondary: { type: Object, default: null },
  /** `(nmId) => number|null` while norms are typed by hand. */
  normOf: { type: Function, default: null },
  /** The grid's currencies — prices, advertising, settlement — for the figures' signs. */
  currencies: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['norm'])

// Columns run oldest first; a phone opens on the newest one.
const index = ref(Math.max(props.columns.length - 1, 0))
watch(
  () => props.columns,
  (columns) => (index.value = Math.max(columns.length - 1, 0)),
)

const column = computed(() => props.columns[index.value] ?? null)
const top = (row, at) => cellText(row, at, props.primary, props.currencies)
const bottom = (row, at) => cellText(row, at, props.secondary, props.currencies, true)
</script>

<template>
  <div v-if="column">
    <div class="mb-sm flex items-center justify-between gap-sm">
      <button
        type="button"
        class="ui-trigger ui-trigger--icon"
        :disabled="index <= 0"
        aria-label="Earlier"
        @click="index -= 1"
      >
        ‹
      </button>
      <span class="text-base font-semibold text-primary">{{ columnLabel(column, period) }}</span>
      <button
        type="button"
        class="ui-trigger ui-trigger--icon"
        :disabled="index >= columns.length - 1"
        aria-label="Later"
        @click="index += 1"
      >
        ›
      </button>
    </div>

    <ul class="divide-y divide-border-subtle rounded-card bg-surface shadow-card">
      <li v-if="totals" class="flex items-center gap-sm bg-canvas px-md py-sm font-semibold">
        <span class="flex-1">Total</span>
        <span class="text-right">
          <span class="block">{{ top(totals, index) }}</span>
          <span v-if="secondary" class="block text-tiny text-muted">{{
            bottom(totals, index)
          }}</span>
        </span>
      </li>
      <li v-if="!rows.length"><DataState kind="empty" layout="bare" /></li>
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
          <span class="block text-tiny text-muted">Total: {{ top(row, 'total') }}</span>
          <label v-if="normOf" class="mt-xs flex items-center gap-xs text-tiny text-muted">
            <!-- No metric name on a phone: it is in the select above, and the
                 full name wrapped the line into three. -->
            {{ addsUp(primary) ? 'Daily target' : 'Target' }}
            <span class="w-20 shrink-0">
              <HeatmapNormInput
                :value="normOf(row.nm_id)"
                :label="`${addsUp(primary) ? 'Daily target' : 'Target'}: ${primary.label} — ${formatSku(row.label) ?? row.nm_id}`"
                @commit="emit('norm', row.nm_id, $event)"
              />
            </span>
          </label>
        </span>
        <span
          class="min-w-20 rounded-btn px-sm py-xs text-right tabular-nums text-primary"
          :style="tints[rowIndex]?.[index]"
        >
          <span class="block text-base">{{ top(row, index) }}</span>
          <span v-if="secondary" class="block text-tiny opacity-70">{{ bottom(row, index) }}</span>
        </span>
      </li>
    </ul>
  </div>
  <DataState v-else kind="empty" layout="bare" />
</template>
