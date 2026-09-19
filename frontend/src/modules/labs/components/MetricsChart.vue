<script setup>
/**
 * A titled block: a metric picker and one plot, used by both pages.
 *
 * What it replaced was a carousel of ten titled slides, each a saved question.
 * The table above this block already lists every metric by day, so the value a
 * chart adds is putting a reader's own handful of them side by side — which
 * makes the picker the feature and the slides scaffolding.
 *
 * The whole window sits on the card's own width — there is no sideways ribbon
 * and no second copy of the plot with a pinned axis beside it. That layout was
 * right for a fortnight and unusable for a year, which is what the window
 * picker above happily asks for.
 *
 * Dumb by contract: the view hands it the matrix, it emits nothing.
 */
import { computed, defineAsyncComponent, ref, watch } from 'vue'

import ChartMetricPicker from '@/modules/labs/components/ChartMetricPicker.vue'
import {
  SKU_DEFAULT_METRICS,
  SKU_METRIC_GROUPS,
  buildMetricChart,
} from '@/modules/labs/metricChart'

// ECharts is ~185 kB gzipped — three times the rest of this route put together.
// Loading it asynchronously keeps it out of the view's own chunk, so the daily
// table (what the page is actually for) paints without waiting for it.
const BaseChart = defineAsyncComponent(() => import('@/core/components/BaseChart.vue'))

const props = defineProps({
  /** A live display matrix (`matrixView` shape). */
  view: { type: Object, required: true },
  /**
   * The metric catalogue this page offers. Defaults to the per-SKU one; the
   * account-wide page passes its own, shorter list, because a sum over cards
   * has no price and no CTR to offer.
   */
  groups: { type: Array, default: () => SKU_METRIC_GROUPS },
  /** Which metrics to open on. */
  defaultMetrics: { type: Array, default: () => SKU_DEFAULT_METRICS },
})

const metrics = ref([...props.defaultMetrics])

/**
 * Which series the cursor is actually on — a plain object, never a `ref`.
 *
 * The tooltip formatter reads it at hover time, so it must be a live holder the
 * built option closes over: made reactive, every mouse-over would rebuild the
 * option and re-render the whole plot under the cursor that is reading it.
 */
const hover = { index: null }

// A different selection is a different series list, so a remembered index would
// point at the wrong metric.
watch(metrics, () => {
  hover.index = null
})

const chart = computed(() =>
  buildMetricChart(props.view, { metrics: metrics.value, groups: props.groups, hover }),
)

/**
 * Tell the chart apart from the day it sits in.
 *
 * A hover anywhere in a day's column answers with every metric — that is the
 * question «what happened on the 5th». A hover that lands ON a line or a bar is
 * a question about that metric, and ECharts already knows which one: `mouseover`
 * fires for the mark under the cursor. Re-showing the tooltip at the same pixel
 * is what makes the narrowed list appear on the frame the mark is entered,
 * rather than on the next mouse move.
 */
function onPlotReady(instance) {
  /** Re-ask for the tooltip where the cursor already is, with `hover` updated. */
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

/** Height enough for several series to have room to move. */
const CHART_HEIGHT = '360px'
</script>

<template>
  <section v-if="chart" class="mt-lg" aria-label="График метрик">
    <h2 class="text-h3 font-semibold text-primary">График</h2>

    <ChartMetricPicker v-model="metrics" :groups="groups" class="mt-sm" />

    <!-- The plot is its own block, on the app's card surface rather than on
         glass: it is the one thing here that is DENSE, and the system's own rule
         is that a pane with figures behind it stops being readable. The three
         pickers above it are the glass.

         Absent entirely when nothing is chosen — the picker's own prompt is the
         whole message then, and an empty card under it is a box of padding. -->
    <div
      v-if="metrics.length"
      class="mt-md rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
    >
      <template v-if="!chart.empty">
        <!-- Legend in HTML: on the canvas it scrolled away with the days it
             labels. -->
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

        <!-- One plot, the card's width. The axis is drawn in the same canvas:
             there is nothing for it to scroll away from any more. -->
        <div class="mt-xs">
          <BaseChart :option="chart.option" :height="CHART_HEIGHT" @ready="onPlotReady" />
        </div>
      </template>

      <p v-else-if="metrics.length" class="py-xl text-center text-base text-muted">
        За выбранный период нет данных по этим метрикам.
      </p>
    </div>
  </section>
</template>
