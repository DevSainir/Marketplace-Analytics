<script setup>
/**
 * SANDBOX — the metrics chart with the ribbon taken away.
 *
 * Same picker, same catalogue, same colours as `MetricsChart.vue`; what differs
 * is that the plot is the card's width instead of a fixed width per day, so a
 * quarter or a year is on screen at once — and that it is drawn the way the
 * reference draws one. `chartScaling.js` holds both halves of that.
 *
 * Dumb by contract: it is handed a matrix and emits nothing.
 */
import { computed, defineAsyncComponent, ref, watch } from 'vue'

import ChartMetricPicker from '@/modules/labs/components/ChartMetricPicker.vue'
import { LONG_DEFAULT_METRICS, buildFittedChart } from '@/modules/labs/chartScaling'
import { SKU_METRIC_GROUPS } from '@/modules/labs/metricChart'

const BaseChart = defineAsyncComponent(() => import('@/core/components/BaseChart.vue'))

const props = defineProps({
  /** A live display matrix (`matrixView` shape). */
  view: { type: Object, required: true },
  /** Block heading. */
  title: { type: String, default: 'График' },
  /** One line under the heading saying what the reader is looking at. */
  note: { type: String, default: '' },
  /** The metric catalogue this page offers. */
  groups: { type: Array, default: () => SKU_METRIC_GROUPS },
  /** Which metrics to open on. */
  defaultMetrics: { type: Array, default: () => LONG_DEFAULT_METRICS },
})

const metrics = ref([...props.defaultMetrics])

/** Live holder the tooltip formatter reads at hover time — never a `ref`. */
const hover = { index: null }

watch(metrics, () => {
  hover.index = null
})

const chart = computed(() =>
  buildFittedChart(props.view, { metrics: metrics.value, groups: props.groups, hover }),
)

/** Narrow the hover to the mark under the cursor — as the live chart does. */
function onPlotReady(instance) {
  const reshow = (params) => {
    const { offsetX, offsetY } = params.event ?? {}
    if (offsetX != null) instance.dispatchAction({ type: 'showTip', x: offsetX, y: offsetY })
  }
  instance.on('mouseover', (params) => {
    if (params.componentType !== 'series') return
    hover.index = params.seriesIndex
    reshow(params)
  })
  instance.on('mouseout', (params) => {
    if (params.componentType !== 'series') return
    hover.index = null
    reshow(params)
  })
}

const CHART_HEIGHT = '360px'
</script>

<template>
  <section v-if="chart" class="mt-lg" :aria-label="title">
    <h2 class="text-h3 font-semibold text-primary">{{ title }}</h2>
    <p v-if="note" class="mt-xs text-tiny text-muted">{{ note }}</p>

    <ChartMetricPicker v-model="metrics" :groups="groups" class="mt-sm" />

    <div
      v-if="metrics.length"
      class="mt-md rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
    >
      <template v-if="!chart.empty">
        <ul class="flex flex-wrap gap-x-md gap-y-xs" aria-label="Показано на графике">
          <li
            v-for="entry in chart.legend"
            :key="entry.name"
            class="flex items-center gap-xs text-tiny text-muted"
          >
            <span
              class="h-2.5 w-2.5 shrink-0 rounded-sm"
              :style="{ backgroundColor: entry.color }"
              aria-hidden="true"
            ></span>
            {{ entry.name }}
          </li>
        </ul>

        <!-- No pinned axis and no scroller: the plot IS the card's width, so
             the y axis has nowhere to scroll away to. -->
        <div class="mt-xs">
          <BaseChart :option="chart.option" :height="CHART_HEIGHT" @ready="onPlotReady" />
        </div>
      </template>

      <p v-else class="py-xl text-center text-base text-muted">
        За выбранный период нет данных по этим метрикам.
      </p>
    </div>
  </section>
</template>
