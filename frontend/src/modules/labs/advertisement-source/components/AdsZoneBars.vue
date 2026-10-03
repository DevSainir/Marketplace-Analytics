<script setup>
/**
 * «Зоны показов»: each bar is one pot of money split into search and the rest.
 *
 * Plain flex bars rather than a chart: two or three rows of one ratio each, and
 * the figure that matters (search's money and share) is printed beside the bar
 * where a chart would hide it in a tooltip. Below `sm` the label moves above
 * its bar so the bar keeps the full width.
 */
import { formatMoney, formatNumber } from '@/core/utils/format'
import { SPLIT_COLORS } from '@/modules/labs/advertisement-source/adsFormat'

const props = defineProps({
  /** `zoneBars` — `{label, search, rest}`, money in each half. */
  bars: { type: Array, required: true },
  /** Days of the window the campaign statistics cover. */
  days: { type: Number, required: true },
  currency: { type: String, default: '' },
})

const LEGEND = [
  { label: 'Поиск', color: SPLIT_COLORS[0] },
  { label: 'Полки и прочее', color: SPLIT_COLORS[1] },
]

/** Percent of the bar, for the width and the label. */
const share = (bar, part) => (part / (bar.search + bar.rest)) * 100

const title = (bar, part) =>
  `${formatMoney(part, props.currency)} · ${formatNumber(Math.round(share(bar, part)))}%`
</script>

<template>
  <div class="rounded-card border border-border-subtle bg-surface p-md shadow-card">
    <h3 class="text-base font-semibold text-primary">Зоны показов</h3>
    <p class="mt-xs text-tiny text-muted">
      Доля измерена по статистике кампаний за {{ days }} дн периода и приложена к деньгам кабинета.
    </p>

    <div class="mt-sm flex flex-wrap gap-md text-tiny text-muted">
      <span v-for="item in LEGEND" :key="item.label" class="inline-flex items-center gap-xs">
        <span class="inline-block h-2.5 w-2.5 rounded-sm" :style="{ background: item.color }" />
        {{ item.label }}
      </span>
    </div>

    <div class="mt-md flex flex-col gap-sm">
      <div
        v-for="bar in bars"
        :key="bar.label"
        class="grid grid-cols-1 items-center gap-xs sm:grid-cols-[9rem_1fr_10rem] sm:gap-md"
      >
        <span class="text-tiny text-muted">{{ bar.label }}</span>
        <div class="flex h-3.5 overflow-hidden rounded-sm bg-canvas">
          <span
            v-for="(part, i) in [bar.search, bar.rest]"
            :key="i"
            class="block h-full"
            :style="{ width: `${share(bar, part).toFixed(2)}%`, background: SPLIT_COLORS[i] }"
            :title="title(bar, part)"
          />
        </div>
        <span class="text-tiny tabular-nums text-muted sm:text-right">
          {{ formatMoney(bar.search, currency) }} ·
          {{ formatNumber(Math.round(share(bar, bar.search))) }}%
        </span>
      </div>
    </div>
  </div>
</template>
