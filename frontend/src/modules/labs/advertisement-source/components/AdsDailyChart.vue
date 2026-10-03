<script setup>
/**
 * «Открутка по дням»: what the кабинет spent each day, by who paid.
 *
 * Two lines, not a stack: a promo day is rare and small, and stacked on top of
 * the balance it disappears into the total — as its own line it is visible as
 * the exception it is. Days are the spend history's charge dates.
 *
 * Ink mirrors `tokens.css` as hex because ECharts paints on a canvas; when a
 * token moves, it moves here too.
 */
import { computed } from 'vue'

import BaseChart from '@/core/components/BaseChart.vue'
import { formatMoney } from '@/core/utils/format'
import { SPLIT_COLORS } from '@/modules/labs/advertisement-source/adsFormat'

const props = defineProps({
  /** `dailySpend` — `{day, balance, promo}` per day. */
  days: { type: Array, required: true },
  currency: { type: String, default: '' },
})

/** `--ui-muted` / `--ui-hairline` / `--ui-ink`. */
const INK_MUTED = '#61616F'
const LINE_HAIRLINE = '#E5E5EF'
const INK = '#12121A'

const SERIES = [
  { key: 'balance', name: 'С баланса' },
  { key: 'promo', name: 'Промо-бонусы' },
]

/** "2026-07-05" -> "05.07" — the axis; the tooltip carries the year. */
const shortDay = (iso) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`
const fullDay = (iso) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`

const option = computed(() => ({
  animation: false,
  grid: { top: 12, right: 12, bottom: 28, left: 8, containLabel: true },
  legend: { show: false },
  tooltip: {
    trigger: 'axis',
    textStyle: { color: INK, fontSize: 12 },
    formatter: (points) =>
      [`<b>${fullDay(props.days[points[0].dataIndex].day)}</b>`]
        .concat(
          points.map((p) => `${p.marker}${p.seriesName}: ${formatMoney(p.value, props.currency)}`),
        )
        .join('<br>'),
  },
  xAxis: {
    type: 'category',
    data: props.days.map((d) => shortDay(d.day)),
    axisLine: { lineStyle: { color: LINE_HAIRLINE } },
    axisTick: { show: false },
    axisLabel: { color: INK_MUTED, fontSize: 10 },
  },
  yAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: LINE_HAIRLINE } },
    axisLabel: { color: INK_MUTED, fontSize: 10, formatter: (v) => formatMoney(v) },
  },
  series: SERIES.map((s, i) => ({
    name: s.name,
    type: 'line',
    smooth: 0.3,
    symbol: 'circle',
    symbolSize: 4,
    color: SPLIT_COLORS[i],
    lineStyle: { width: 1.8 },
    areaStyle: { color: SPLIT_COLORS[i], opacity: 0.12 },
    data: props.days.map((d) => d[s.key]),
  })),
}))
</script>

<template>
  <div class="rounded-card border border-border-subtle bg-surface p-md shadow-card">
    <div class="flex flex-wrap gap-md text-tiny text-muted">
      <span v-for="(s, i) in SERIES" :key="s.key" class="inline-flex items-center gap-xs">
        <span class="inline-block h-0.5 w-3 rounded-sm" :style="{ background: SPLIT_COLORS[i] }" />
        {{ s.name }}
      </span>
    </div>
    <BaseChart :option="option" height="280px" />
  </div>
</template>
