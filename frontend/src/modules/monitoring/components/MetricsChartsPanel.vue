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

import { buildChartSpecs } from '@/modules/monitoring/chartSpecs'

// ECharts is ~185 kB gzipped — three times the rest of this route put together.
// Loading it asynchronously keeps it out of the view's own chunk, so the daily
// table (what the page is actually for) paints without waiting for a charting
// library, and the block fills itself in a moment later.
const BaseChart = defineAsyncComponent(() => import('@/core/components/BaseChart.vue'))

/**
 * Plot height. Held here rather than in a class so the wrapper can RESERVE it
 * while the async component is still loading — otherwise the card collapses and
 * snaps back open a moment later. No spacing token comes near this size; it is
 * a plot's proportions, not layout rhythm.
 */
const CHART_HEIGHT = '340px'

const props = defineProps({
  /** The store's live display matrix (`matrixView`). */
  view: { type: Object, required: true },
})

const charts = computed(() => buildChartSpecs(props.view))

const activeIndex = ref(0)
const active = computed(() => charts.value[activeIndex.value] ?? null)

// A new SKU or a new window rebuilds the slides; the tab that was open may no
// longer exist, so fall back to the first rather than render nothing.
watch(charts, (list) => {
  if (activeIndex.value >= list.length) activeIndex.value = 0
})

/** Step the carousel, wrapping at both ends («‹» from the first goes last). */
function step(delta) {
  const count = charts.value.length
  if (count) activeIndex.value = (activeIndex.value + delta + count) % count
}

/** The tab buttons, so an arrow key can move focus onto the one it selects. */
const tabRefs = ref([])

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
  tabRefs.value[activeIndex.value]?.focus()
}
</script>

<template>
  <section v-if="charts.length" class="mt-lg" aria-label="Графики">
    <h2 class="text-h3 font-semibold text-primary">Графики</h2>
    <p class="mt-xs max-w-3xl text-tiny font-medium text-muted">
      Те же значения, что и в таблице выше, по дням выбранного периода. Наведите курсор, чтобы
      увидеть точные числа за день.
    </p>

    <div
      class="mt-sm rounded-card border border-border-subtle bg-surface p-lg shadow-card outline-none focus-visible:ring-2 focus-visible:ring-action phone:p-md"
      tabindex="0"
      role="group"
      aria-label="Карусель графиков: стрелки влево и вправо переключают график"
      @keydown="onArrowKey"
    >
      <!-- Tab strip = the carousel's position indicator. It scrolls sideways on
           a narrow screen instead of wrapping into three ragged rows. -->
      <div role="tablist" aria-label="Графики метрик" class="flex gap-xs overflow-x-auto pb-xs">
        <button
          v-for="(chart, index) in charts"
          :key="chart.key"
          :ref="(el) => (tabRefs[index] = el)"
          type="button"
          role="tab"
          :aria-selected="index === activeIndex"
          :tabindex="index === activeIndex ? 0 : -1"
          class="shrink-0 rounded-btn px-md py-xs text-tiny font-medium transition phone:py-sm"
          :class="
            index === activeIndex
              ? 'bg-action text-white shadow-soft'
              : 'text-muted hover:bg-hover hover:text-primary'
          "
          @click="activeIndex = index"
        >
          {{ chart.tab }}
        </button>
      </div>

      <div v-if="active" class="mt-md flex items-center gap-sm">
        <button
          type="button"
          class="flex h-8 w-8 shrink-0 items-center justify-center rounded-btn border border-border-subtle bg-canvas text-h3 leading-none text-primary transition hover:bg-hover phone:h-10 phone:w-10"
          aria-label="Предыдущий график"
          @click="step(-1)"
        >
          ‹
        </button>
        <h3 class="min-w-0 flex-1 text-center text-base font-semibold text-primary">
          {{ active.title }}
        </h3>
        <button
          type="button"
          class="flex h-8 w-8 shrink-0 items-center justify-center rounded-btn border border-border-subtle bg-canvas text-h3 leading-none text-primary transition hover:bg-hover phone:h-10 phone:w-10"
          aria-label="Следующий график"
          @click="step(1)"
        >
          ›
        </button>
      </div>

      <!-- `key` forces a fresh canvas per slide: ECharts keeps the previous
           chart's axis extents when only the option object changes, and a ₽
           axis inherited by a % chart is worse than a re-init. -->
      <div v-if="active && !active.empty" class="mt-sm" :style="{ height: CHART_HEIGHT }">
        <BaseChart :key="active.key" :option="active.option" :height="CHART_HEIGHT" />
      </div>
      <p v-else-if="active" class="mt-sm py-xl text-center text-base text-muted">
        За выбранный период нет данных для этого графика.
      </p>
    </div>
  </section>
</template>
