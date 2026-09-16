<script setup>
/**
 * The summary's line chart: grid, one path per series, crosshair and tooltip.
 *
 * Drawn declaratively rather than through `innerHTML` — the geometry is
 * computed in `chartGeometry.js` and bound into the template, so Vue owns every
 * node and the hover state is plain reactive data.
 *
 * Measured in real pixels (see `useChartWidth`): a fixed viewBox stretched to
 * the container magnifies the labels along with the plot, which is what made
 * the first version look blown up next to the rest of the page.
 */
import { computed, ref } from 'vue'

import { formatMoney } from '@/core/utils/format'
import { MARGIN, buildScales, labelStep, linePath } from '@/modules/summary/chartGeometry'
import { useChartWidth } from '@/modules/summary/useChartWidth'

const props = defineProps({
  /** `[{ name, color, values: (number|null)[] }]` — one entry per line. */
  series: { type: Array, required: true },
  /** ISO day per point, same length as every series' values. */
  labels: { type: Array, required: true },
  height: { type: Number, default: 232 },
  /** Currency code for the tooltip; empty renders bare numbers. */
  currency: { type: String, default: '' },
  /** Render values as plain counts rather than money (the orders chart). */
  plain: { type: Boolean, default: false },
})

const { el, width } = useChartWidth()
const hovered = ref(null)

const scales = computed(() =>
  buildScales({
    width: width.value,
    height: props.height,
    series: props.series,
    count: props.labels.length,
  }),
)

const paths = computed(() =>
  props.series.map((line) => ({
    ...line,
    d: linePath(line.values, scales.value.x, scales.value.y),
  })),
)

const xLabels = computed(() => {
  const step = labelStep(props.labels.length, scales.value.innerWidth)
  return props.labels
    .map((day, index) => ({ day, index }))
    .filter((entry) => entry.index % step === 0)
    .map((entry) => ({
      key: entry.day,
      x: scales.value.x(entry.index),
      text: `${entry.day.slice(8, 10)}.${entry.day.slice(5, 7)}`,
    }))
})

/** The hovered point of each series, for the tooltip and the dots. */
const readout = computed(() => {
  if (hovered.value === null) return null
  const index = hovered.value
  return {
    index,
    x: scales.value.x(index),
    day: props.labels[index],
    points: props.series.map((line) => ({
      name: line.name,
      color: line.color,
      value: line.values[index],
      y: Number.isFinite(line.values[index]) ? scales.value.y(line.values[index]) : null,
    })),
  }
})

/** Tooltip anchored beside the crosshair, flipped when it would overflow. */
const tooltipStyle = computed(() => {
  if (!readout.value) return {}
  const flip = readout.value.x > width.value - 180
  return flip
    ? { right: `${width.value - readout.value.x + 14}px`, top: '8px' }
    : { left: `${readout.value.x + 14}px`, top: '8px' }
})

function show(event) {
  const box = event.currentTarget.getBoundingClientRect()
  const local = ((event.clientX - box.left) / box.width) * width.value
  const count = props.labels.length
  if (count === 0) return
  const ratio = (local - MARGIN.left) / scales.value.innerWidth
  hovered.value = Math.max(0, Math.min(count - 1, Math.round(ratio * (count - 1))))
}

function render(value) {
  if (!Number.isFinite(value)) return '—'
  return props.plain
    ? Math.round(value).toLocaleString('ru-RU')
    : formatMoney(value, props.currency)
}
</script>

<template>
  <div ref="el" class="relative">
    <svg
      :viewBox="`0 0 ${width} ${height}`"
      :height="height"
      class="w-full select-none"
      role="img"
      @pointermove="show"
      @pointerleave="hovered = null"
    >
      <g class="sum-grid">
        <line
          v-for="tick in scales.ticks"
          :key="tick.value"
          :x1="MARGIN.left"
          :x2="scales.plotRight"
          :y1="tick.y"
          :y2="tick.y"
        />
      </g>

      <text
        v-for="tick in scales.ticks"
        :key="`t-${tick.value}`"
        :x="MARGIN.left - 8"
        :y="tick.y + 3.4"
        text-anchor="end"
        class="sum-axis"
      >
        {{ tick.label }}
      </text>

      <text
        v-for="label in xLabels"
        :key="label.key"
        :x="label.x"
        :y="height - 8"
        text-anchor="middle"
        class="sum-axis"
      >
        {{ label.text }}
      </text>

      <line
        v-if="scales.hasNegative"
        class="sum-zero"
        :x1="MARGIN.left"
        :x2="scales.plotRight"
        :y1="scales.zeroY"
        :y2="scales.zeroY"
      />

      <path
        v-for="line in paths"
        :key="line.name"
        :d="line.d"
        :stroke="line.color"
        fill="none"
        stroke-width="2"
        stroke-linejoin="round"
        stroke-linecap="round"
      />

      <template v-if="readout">
        <line
          class="sum-cross"
          :x1="readout.x"
          :x2="readout.x"
          :y1="MARGIN.top"
          :y2="scales.plotBottom"
        />
        <circle
          v-for="point in readout.points.filter((p) => p.y !== null)"
          :key="point.name"
          :cx="readout.x"
          :cy="point.y"
          r="4"
          :fill="point.color"
          stroke="var(--ui-surface)"
          stroke-width="2"
        />
      </template>
    </svg>

    <div v-if="readout" class="ui-glass ui-glass--pop sum-tip" :style="tooltipStyle">
      <div class="sum-tip__day">{{ readout.day.split('-').reverse().join('.') }}</div>
      <div v-for="point in readout.points" :key="point.name" class="sum-tip__row">
        <span class="sum-tip__name">
          <span class="sum-tip__dot" :style="{ background: point.color }"></span>
          {{ point.name }}
        </span>
        <span class="sum-tip__value">{{ render(point.value) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped src="@/modules/summary/components/SummaryLineChart.css"></style>
