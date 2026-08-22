<script setup>
/**
 * «Графики» — the chart block between the daily table and the stock tables.
 *
 * A carousel rather than a wall of thumbnails: the metrics that matter here are
 * day series over a 30-day window, and eight of those shrunk into a grid are
 * eight sparklines nobody can read a number off. One full-width chart at a time
 * keeps the day axis legible, and the tab strip doubles as the carousel's
 * position indicator, so a manager who wants «Расходы» goes straight there
 * instead of pressing «next» five times.
 *
 * It draws the SAME matrix the table above renders, so a manual edit or an undo
 * moves the chart with the table.
 *
 * Dumb by contract: the view hands it the matrix, it emits nothing.
 */
import { computed, defineAsyncComponent, nextTick, ref, watch } from 'vue'

import { vDragScroll } from '@/core/utils/dragScroll'
import ChartCarouselHeader from '@/modules/monitoring/components/ChartCarouselHeader.vue'
import ChartMetricPicker from '@/modules/monitoring/components/ChartMetricPicker.vue'
import {
  DEFAULT_OVERVIEW,
  OVERVIEW_METRICS,
  buildChartSpecs,
} from '@/modules/monitoring/chartSpecs'
import { useChartRibbon } from '@/modules/monitoring/useChartRibbon'

// ECharts is ~185 kB gzipped — three times the rest of this route put together.
// Loading it asynchronously keeps it out of the view's own chunk, so the daily
// table (what the page is actually for) paints without waiting for a charting
// library, and the block fills itself in a moment later.
const BaseChart = defineAsyncComponent(() => import('@/core/components/BaseChart.vue'))

const props = defineProps({
  /** The store's live display matrix (`matrixView`, or the aggregate one). */
  view: { type: Object, required: true },
  /**
   * Which chart list to draw. Defaults to the per-SKU set; the account-wide
   * «Графики» page passes its own shorter one, so both pages share this
   * component, its ribbon and its carousel rather than growing a second copy.
   */
  buildSpecs: { type: Function, default: buildChartSpecs },
  /** Window totals for the funnel slide; computed server-side, never here. */
  totals: { type: Object, default: null },
  heading: { type: String, default: 'Графики' },
  hint: {
    type: String,
    default:
      'Те же значения, что и в таблице выше, по дням выбранного периода. Наведите курсор, ' +
      'чтобы увидеть точные числа за день.',
  },
})

/**
 * «Общий» is the one slide with no fixed question: the reader ticks the
 * metrics whose relationship they are chasing. Held here rather than in the
 * spec module because it is view state, and it survives switching tabs.
 */
const overview = ref([...DEFAULT_OVERVIEW])
/** «Значения» or «Индекс» — see `OVERVIEW_MODES`. */
const overviewMode = ref('absolute')
const metricChoices = OVERVIEW_METRICS

const charts = computed(() =>
  props.buildSpecs(props.view, {
    overview: overview.value,
    mode: overviewMode.value,
    totals: props.totals,
  }),
)

const activeIndex = ref(0)
const active = computed(() => charts.value[activeIndex.value] ?? null)

// The plot is drawn at its natural width and scrolled sideways; the y axis is
// pinned beside it like the table's frozen first column.
const { scroller, plotWidth, axisOption, plotOption, onUserSteer } = useChartRibbon(active)
const axisWidth = computed(() => `${active.value?.axisGutter ?? 74}px`)

// A new SKU or a new window rebuilds the slides; the tab that was open may no
// longer exist, so fall back to the first rather than render nothing.
watch(charts, (list) => {
  if (activeIndex.value >= list.length) activeIndex.value = 0
})

/**
 * Plot height, per slide (the funnel's three panels need more than one plot
 * does). Read off the spec rather than hard-coded so the wrapper can RESERVE
 * it while the async component is still loading — otherwise the card collapses
 * and snaps back open a moment later. No spacing token comes near these sizes;
 * they are a plot's proportions, not layout rhythm.
 */
const chartHeight = computed(() => active.value?.height ?? '340px')

/** Step the carousel, wrapping at both ends («‹» from the first goes last). */
function step(delta) {
  const count = charts.value.length
  if (count) activeIndex.value = (activeIndex.value + delta + count) % count
}

/** The header owns the tab buttons, so focus can follow an arrow-key move. */
const header = ref(null)

/**
 * ←/→ step the carousel, but only once the block has the keyboard: the page's
 * own arrow keys belong to whatever the user is doing in the table above, and
 * a document-level listener would hijack them from every input on the page.
 * `tabindex="0"` on the card is what lets it take focus, and clicking a tab
 * already puts focus inside it.
 *
 * Focus then follows the selection onto the new tab — the ARIA tabs pattern,
 * and without it the focus ring is left behind on the tab you arrowed away
 * from, pointing at a chart that is no longer on screen.
 */
async function onArrowKey(event) {
  if (event.key === 'ArrowLeft') step(-1)
  else if (event.key === 'ArrowRight') step(1)
  else return
  // Stop the browser scrolling the tab strip sideways under the slide change.
  event.preventDefault()
  await nextTick()
  header.value?.focusActiveTab(activeIndex.value)
}
</script>

<template>
  <section v-if="charts.length" class="mt-lg" :aria-label="heading">
    <h2 class="text-h3 font-semibold text-primary">{{ heading }}</h2>
    <p class="mt-xs max-w-3xl text-tiny font-medium text-muted">{{ hint }}</p>

    <div
      class="mt-sm rounded-card border border-border-subtle bg-surface p-lg shadow-card outline-none focus-visible:ring-2 focus-visible:ring-action phone:p-md"
      tabindex="0"
      role="group"
      aria-label="Карусель графиков: стрелки влево и вправо переключают график"
      @keydown="onArrowKey"
    >
      <ChartCarouselHeader
        ref="header"
        :charts="charts"
        :active-index="activeIndex"
        :title="active?.title ?? ''"
        @select="activeIndex = $event"
        @step="step"
      />

      <!-- The picker rides above «Общий» only: every other slide is a saved
           question and its metrics are the answer. -->
      <ChartMetricPicker
        v-if="active?.pickable"
        v-model="overview"
        v-model:mode="overviewMode"
        :choices="metricChoices"
      />

      <template v-if="active && !active.empty">
        <!-- Legend above the plot, in HTML: on the canvas it scrolled away with
             the days it labels. -->
        <ul class="mt-sm flex flex-wrap gap-x-md gap-y-xs">
          <li
            v-for="entry in active.legend"
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

        <!-- The chart's «frozen column»: the y axis stands still while the days
             scroll past it, the way the metrics table pins its metric names. -->
        <!-- A funnel has no day ribbon and no frozen column: it is the whole
             window in one shape, so it takes the card's full width. -->
        <div v-if="active.funnel" class="mt-xs" :style="{ height: chartHeight }">
          <BaseChart :key="active.key" :option="active.option" :height="chartHeight" />
        </div>

        <div v-else class="mt-xs flex" :style="{ height: chartHeight }">
          <!-- The column is RESERVED by this wrapper rather than sized by the
               chart inside it. The chart is loaded asynchronously, so until it
               arrives it occupies nothing — and the ribbon beside it, being
               `flex-1`, opened 74px too wide and scrolled to a stale end,
               parking the newest days just off screen.

               «Воронка 1» draws no y axis at all, so it reserves nothing and
               the plot runs the full width of the card. -->
          <div
            v-if="active.axisGutter"
            class="shrink-0"
            :style="{ width: axisWidth, height: chartHeight }"
          >
            <BaseChart :key="`axis-${active.key}`" :option="axisOption" :height="chartHeight" />
          </div>
          <div
            ref="scroller"
            v-drag-scroll
            class="chart-scroll min-w-0 flex-1"
            @wheel.passive="onUserSteer"
            @pointerdown.passive="onUserSteer"
          >
            <div :style="{ minWidth: '100%', width: plotWidth, height: chartHeight }">
              <BaseChart :key="active.key" :option="plotOption" :height="chartHeight" />
            </div>
          </div>
        </div>
      </template>
      <p v-else-if="active" class="mt-sm py-xl text-center text-base text-muted">
        За выбранный период нет данных для этого графика.
      </p>
    </div>
  </section>
</template>

<style scoped>
/* Native scroll, matching the metrics table's ribbon exactly (`.matrix-scroll`):
   the scrollbar is hidden because macOS overlay scrollbars otherwise pin a white
   track over the card, and `v-drag-scroll` supplies wheel + drag panning.

   `overflow: auto`, NOT `overflow-y: hidden`. Pinning the vertical axis here
   stopped the page scrolling while the cursor was over a chart — and it was
   never this stylesheet's call to make: the directive already decides, per
   gesture, whether a trackpad swipe is vertical (page scrolls, ribbon held
   still via `.wheel-axis-locked`) or sideways (ribbon scrolls natively). */
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
