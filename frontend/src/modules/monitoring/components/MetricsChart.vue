<script setup>
/**
 * A metric picker and one plot, nothing else — used by both pages.
 *
 * What it replaced was a carousel of ten titled slides, each a saved question.
 * The table above this block already lists every metric by day, so the value a
 * chart adds is putting a reader's own two or three of them side by side —
 * which makes the picker the feature and the slides scaffolding.
 *
 * No heading and no chart title: it sits under the tables whose numbers it
 * draws, and a caption saying «Графики» over a graph is a word doing no work.
 *
 * Dumb by contract: the view hands it the matrix, it emits nothing.
 */
import { computed, defineAsyncComponent, ref } from 'vue'

import { vDragScroll } from '@/core/utils/dragScroll'
import ChartMetricPicker from '@/modules/monitoring/components/ChartMetricPicker.vue'
import {
  CHART_MODES,
  SKU_DEFAULT_METRICS,
  SKU_METRIC_GROUPS,
  buildMetricChart,
} from '@/modules/monitoring/metricChart'
import { useChartRibbon } from '@/modules/monitoring/useChartRibbon'

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
const mode = ref('absolute')
const modes = CHART_MODES

const chart = computed(() =>
  buildMetricChart(props.view, {
    metrics: metrics.value,
    groups: props.groups,
    mode: mode.value,
  }),
)

/** Height enough for two or three series to have room to move. */
const CHART_HEIGHT = '360px'

// The plot is drawn at its natural width and scrolled sideways; the y axis is
// pinned beside it like the table's frozen first column.
const { scroller, plotWidth, axisOption, plotOption } = useChartRibbon(chart)
const axisWidth = computed(() => `${chart.value?.axisGutter ?? 74}px`)
</script>

<template>
  <section v-if="chart" class="mt-lg" aria-label="График метрик">
    <div class="rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md">
      <ChartMetricPicker v-model="metrics" v-model:mode="mode" :groups="groups" :modes="modes" />

      <template v-if="!chart.empty">
        <!-- Legend in HTML: on the canvas it scrolled away with the days it
             labels. -->
        <ul class="mt-md flex flex-wrap gap-x-md gap-y-xs">
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

        <!-- The y axis stands still while the days scroll past it, the way the
             metrics table pins its metric names. -->
        <div class="mt-xs flex" :style="{ height: CHART_HEIGHT }">
          <BaseChart
            key="axis"
            class="shrink-0"
            :option="axisOption"
            :height="CHART_HEIGHT"
            :style="{ width: axisWidth }"
          />
          <div ref="scroller" v-drag-scroll class="chart-scroll min-w-0 flex-1">
            <div :style="{ minWidth: '100%', width: plotWidth, height: CHART_HEIGHT }">
              <BaseChart key="plot" :option="plotOption" :height="CHART_HEIGHT" />
            </div>
          </div>
        </div>
      </template>

      <p v-else-if="metrics.length" class="py-xl text-center text-base text-muted">
        За выбранный период нет данных по этим метрикам.
      </p>
    </div>
  </section>
</template>

<style scoped>
/* Native scroll, matching the metrics table's ribbon exactly
   (`.matrix-scroll`): the scrollbar is hidden because macOS overlay scrollbars
   otherwise pin a white track over the card, and `v-drag-scroll` supplies wheel
   and drag panning.

   `overflow: auto`, not `overflow-y: hidden` — the directive decides per
   gesture whether a trackpad swipe is vertical (the page scrolls, the ribbon
   holds still) or sideways; pinning the axis here stopped the page scrolling
   under the cursor. */
.chart-scroll {
  overflow: auto;
  scrollbar-width: none;
}
.chart-scroll::-webkit-scrollbar {
  display: none;
}
.chart-scroll.drag-scrolling {
  cursor: grabbing;
  user-select: none;
}
.chart-scroll.wheel-axis-locked {
  overflow-x: hidden;
}
</style>
