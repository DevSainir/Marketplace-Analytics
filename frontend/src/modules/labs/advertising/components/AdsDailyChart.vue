<script setup>
/**
 * «Открутка по дням»: spend, the bonus part of it, and ДРР от продаж.
 *
 * ДРР is on its own right-hand percent scale, as asked, so its line does not
 * flatten against money in the hundreds of thousands. Two scales on one plot
 * invite reading the crossings as meaningful, so the ДРР line is set apart
 * three ways: dashed, its own hue, and an axis labelled in percent. It stops on
 * the last settled day — past it there are no sales to divide by, and a gap is
 * honest where a zero would read as «реклама окупилась бесплатно».
 *
 * With bonuses hidden the blue line is «Расход» — everything the campaigns
 * spent. With them shown it becomes «Расход с баланса», the spend minus what
 * WB's bonus paid, and the bonus gets its own line: the two then add up to the
 * day's whole spend instead of one being a part of the other.
 *
 * Ink mirrors `tokens.css` as hex because ECharts paints on a canvas.
 */
import { computed } from 'vue'

import BaseChart from '@/core/components/BaseChart.vue'
import { formatMoney } from '@/core/utils/format'
import { SERIES, dateRu, ratioPct } from '@/modules/labs/advertising/adsFormat'
import { drrOf } from '@/modules/labs/advertising/skuModel'

const props = defineProps({
  /** API `days`. */
  days: { type: Array, required: true },
  currency: { type: String, default: '' },
  showBonus: { type: Boolean, default: false },
  /** False when spend and sales are in different currencies — no ДРР line then. */
  showDrr: { type: Boolean, default: true },
})

/** `--ui-muted` / `--ui-hairline` / `--ui-ink`. */
const INK_MUTED = '#61616F'
const LINE_HAIRLINE = '#E5E5EF'
const INK = '#12121A'

const spendName = computed(() => (props.showBonus ? 'Расход с баланса' : 'Расход'))

const legend = computed(() => [
  { key: 'spend', name: spendName.value, dashed: false },
  ...(props.showBonus ? [{ key: 'bonus', name: 'Промо-бонусы', dashed: false }] : []),
  ...(props.showDrr ? [{ key: 'drr', name: 'ДРР от продаж', dashed: true }] : []),
])

/**
 * Per-day ДРР from the seller's own money — the day's spend minus WB's bonus,
 * whatever the bonus switch shows — over the day's sales. `null` past the
 * settlement, and on a day whose returns outweighed its sales.
 */
const drr = computed(() =>
  props.days.map((d) =>
    d.sales === null ? null : drrOf(Number(d.spend) - Number(d.bonus), Number(d.sales)),
  ),
)

function moneyLine(name, color, values) {
  return {
    name,
    type: 'line',
    smooth: 0.3,
    symbol: 'circle',
    symbolSize: 4,
    color,
    lineStyle: { width: 2 },
    areaStyle: { color, opacity: 0.1 },
    data: values,
  }
}

const option = computed(() => ({
  animation: false,
  grid: { top: 16, right: 8, bottom: 28, left: 8, containLabel: true },
  legend: { show: false },
  tooltip: {
    trigger: 'axis',
    textStyle: { color: INK, fontSize: 12 },
    formatter: (points) =>
      [`<b>${dateRu(props.days[points[0].dataIndex].day)}</b>`]
        .concat(
          points.map((p) =>
            p.seriesName === 'ДРР от продаж'
              ? `${p.marker}${p.seriesName}: ${ratioPct(p.value === null ? null : p.value / 100)}`
              : `${p.marker}${p.seriesName}: ${formatMoney(p.value, props.currency)}`,
          ),
        )
        .join('<br>'),
  },
  xAxis: {
    type: 'category',
    data: props.days.map((d) => `${d.day.slice(8, 10)}.${d.day.slice(5, 7)}`),
    axisLine: { lineStyle: { color: LINE_HAIRLINE } },
    axisTick: { show: false },
    axisLabel: { color: INK_MUTED, fontSize: 10 },
  },
  yAxis: [
    {
      type: 'value',
      splitLine: { lineStyle: { color: LINE_HAIRLINE } },
      axisLabel: { color: INK_MUTED, fontSize: 10, formatter: (v) => formatMoney(v) },
    },
    {
      type: 'value',
      show: props.showDrr,
      // ДРР is withheld rather than negative, so the axis starts at zero and
      // the line never floats over an empty band below it.
      min: 0,
      splitLine: { show: false },
      axisLabel: { color: SERIES.drr, fontSize: 10, formatter: (v) => `${v}%` },
    },
  ],
  series: [
    moneyLine(
      spendName.value,
      SERIES.spend,
      props.days.map((d) => Number(d.spend) - (props.showBonus ? Number(d.bonus) : 0)),
    ),
    ...(props.showBonus
      ? [
          moneyLine(
            'Промо-бонусы',
            SERIES.bonus,
            props.days.map((d) => Number(d.bonus)),
          ),
        ]
      : []),
    ...(props.showDrr
      ? [
          {
            name: 'ДРР от продаж',
            type: 'line',
            yAxisIndex: 1,
            smooth: 0.3,
            symbol: 'circle',
            symbolSize: 4,
            color: SERIES.drr,
            lineStyle: { width: 2, type: 'dashed' },
            connectNulls: false,
            data: drr.value.map((r) => (r === null ? null : Math.round(r * 1000) / 10)),
          },
        ]
      : []),
  ],
}))
</script>

<template>
  <div class="rounded-card border border-border-subtle bg-surface p-md shadow-card">
    <div class="flex flex-wrap gap-md text-tiny text-muted">
      <span v-for="item in legend" :key="item.key" class="inline-flex items-center gap-xs">
        <span
          class="inline-block w-4 border-t-2"
          :class="item.dashed ? 'border-dashed' : ''"
          :style="{ borderColor: SERIES[item.key] }"
        />
        {{ item.name }}
      </span>
    </div>
    <BaseChart :option="option" height="300px" />
  </div>
</template>
