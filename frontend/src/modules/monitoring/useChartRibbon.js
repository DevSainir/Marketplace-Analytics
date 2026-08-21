/**
 * The scrolling half of a chart: how wide the plot is drawn, where it starts,
 * and the split between the pinned axis and the ribbon that moves.
 *
 * Extracted from `MetricsChartsPanel` because none of it is about the carousel
 * — it is the geometry of one plot, and keeping it in the component pushed the
 * component past the 250-line limit while burying the tab/slide logic that IS
 * specific to it.
 *
 * The shape mirrors the metrics table above: a wide ribbon scrolled sideways
 * (wheel, drag or trackpad, all via `v-drag-scroll`) with the labels that name
 * things held still beside it.
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { axisOnlyOption, plotOnlyOption } from '@/modules/monitoring/chartOptions'

/**
 * Width per day.
 *
 * Squeezing a month into the card is what made the charts unreadable: at ~24px
 * a day two bars have no room to be two bars, and a line's daily moves are
 * sub-pixel. 52px is about the width of a «15.08» label plus air, so the day
 * axis reads without thinning and a line gets a visible dot per day.
 */
const DAY_WIDTH_PX = 52

/**
 * @param {import('vue').Ref<{option: object, dayCount: number, key: string}|null>} active
 *   The slide on screen.
 * @returns {{
 *   scroller: import('vue').Ref<HTMLElement|null>,
 *   plotWidth: import('vue').ComputedRef<string>,
 *   axisOption: import('vue').ComputedRef<object|null>,
 *   plotOption: import('vue').ComputedRef<object|null>,
 * }}
 */
export function useChartRibbon(active) {
  const scroller = ref(null)

  const plotWidth = computed(() => `${(active.value?.dayCount ?? 0) * DAY_WIDTH_PX}px`)

  // One chart, rendered twice: the axis stands still, the plot scrolls past it.
  const axisOption = computed(() =>
    active.value ? axisOnlyOption(active.value.option, active.value.axisGutter) : null,
  )
  const plotOption = computed(() => (active.value ? plotOnlyOption(active.value.option) : null))

  /**
   * Open on the NEWEST day, the way the metrics table's ribbon does. History
   * runs off to the left; landing on a month-old Monday would make every chart
   * look like it was missing the data it actually has.
   */
  async function scrollToLatest() {
    await nextTick()
    const el = scroller.value
    if (el) el.scrollLeft = el.scrollWidth
  }

  // A new slide re-renders the plot at a new width, so the position has to be
  // retaken rather than kept.
  watch(() => active.value?.key, scrollToLatest)
  onMounted(scrollToLatest)

  return { scroller, plotWidth, axisOption, plotOption }
}
